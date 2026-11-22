import configparser
import json
import re
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

try:
    import jinja2
except ImportError:          # the macro tests need it: pip install jinja2
    jinja2 = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "opencreator-plugin.json").read_text())


def klipper_config():
    # Klipper reads its config like this: inline # and ; are comments.
    cp = configparser.RawConfigParser(strict=False, inline_comment_prefixes=("#", ";"))
    cp.read_string((ROOT / MANIFEST["klipper_config"]).read_text())
    return cp


class ManifestTest(unittest.TestCase):
    def test_files_exist(self):
        paths = [MANIFEST["klipper_config"]] + list(MANIFEST["scripts"].values())
        for rel in paths:
            self.assertTrue((ROOT / rel).is_file(), rel)
        self.assertTrue((ROOT / "moonraker" / "oc-spoolman.conf").is_file())

    def test_moonraker_template_is_commented_out(self):
        # An active placeholder address would have AFC wait on a server that isn't there.
        for line in (ROOT / "moonraker" / "oc-spoolman.conf").read_text().splitlines():
            self.assertTrue(not line.strip() or line.startswith("#"), line)


def kalico_command(line):
    """The command name Kalico's G-code parser (klippy/gcode.py) reads from a line."""
    parts = re.split("([A-Z_]+|[A-Z*])", line.upper())
    cmd = "".join(parts[:3]).strip()
    if re.match(r"^_*[A-Z][0-9]+_[A-Z0-9_]+(?:\s|$)", line.upper()):
        cmd = line.split(None, 1)[0].upper()
    return cmd


class CommandNameTest(unittest.TestCase):
    def test_every_command_parses_as_itself(self):
        # A name like _OC_SPOOLMAN_C5_TOOL_SELECT parses as "_OC_SPOOLMAN_C5": Klipper then
        # reports an unknown command and carries on, so the real command silently never runs.
        cfg = klipper_config()
        names = set()
        for section in cfg.sections():
            if section.startswith("gcode_macro "):
                names.add(section.split(None, 1)[1].upper())
                if cfg.has_option(section, "rename_existing"):
                    names.add(cfg.get(section, "rename_existing").upper())
                for line in cfg.get(section, "gcode").splitlines():
                    m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)(?:\s|$)", line)
                    if m and not line.strip().startswith("{"):
                        names.add(m.group(1).upper())
        for name in sorted(names):
            self.assertEqual(kalico_command(name + " T=0"), name, name)


class MacroRenderTest(unittest.TestCase):
    """Renders the macros the way Klipper does, against a fake printer status."""

    def setUp(self):
        if jinja2 is None:
            self.skipTest("jinja2 not installed")
        self.cfg = klipper_config()
        self.env = jinja2.Environment("{%", "%}", "{", "}")
        self.calls, self.info, self.vars = [], [], {}
        self.lanes = {"extruder%d" % i: {"spool_id": None, "material": "", "color": ""} for i in range(4)}
        self.extruder, self.state, self.spoolman = "extruder1", "standby", "http://10.0.0.5:7912"

    def printer(self):
        p = {"toolhead": {"extruder": self.extruder}, "print_stats": {"state": self.state},
             "AFC": {"spoolman": self.spoolman, "lanes": list(self.lanes)},
             "save_variables": {"variables": self.vars}}
        p.update({"AFC_lane " + k: v for k, v in self.lanes.items()})
        return p

    def run_macro(self, name, **params):
        def raise_error(msg):
            raise RuntimeError(msg)

        def remote(method, **kw):
            self.calls.append((method, kw))
            return ""

        def respond(msg):
            self.info.append(msg)
            return ""

        tmpl = self.env.from_string(self.cfg.get("gcode_macro " + name, "gcode"))
        out = tmpl.render(printer=self.printer(), params={k: str(v) for k, v in params.items()},
                          rawparams=" ".join("%s=%s" % kv for kv in params.items()),
                          action_raise_error=raise_error,
                          action_call_remote_method=remote, action_respond_info=respond)
        return [l.strip() for l in out.splitlines() if l.strip()]

    def test_set_tool_defaults_to_active_tool(self):
        lines = self.run_macro("SPOOLMAN_SET_TOOL", SPOOL=174)
        self.assertEqual(lines, ["SET_SPOOL_ID LANE=extruder1 SPOOL_ID=174",
                                 "_SPOOLMAN_SET_TOOL_DONE TOOL=1 SPOOL=174 ACTIVATE=1"])

    def test_set_other_tool_does_not_activate(self):
        lines = self.run_macro("SPOOLMAN_SET_TOOL", TOOL=3, SPOOL=12)
        self.assertIn("_SPOOLMAN_SET_TOOL_DONE TOOL=3 SPOOL=12 ACTIVATE=0", lines)

    def test_same_spool_skips_lookup(self):
        self.lanes["extruder1"]["spool_id"] = 174
        lines = self.run_macro("SPOOLMAN_SET_TOOL", SPOOL=174)
        self.assertFalse(any(l.startswith("SET_SPOOL_ID") for l in lines), lines)

    def test_spool_moves_off_other_tool(self):
        self.lanes["extruder0"]["spool_id"] = 174
        lines = self.run_macro("SPOOLMAN_SET_TOOL", SPOOL=174)
        self.assertEqual(lines[0], "SET_SPOOL_ID LANE=extruder0 SPOOL_ID=")
        self.assertIn("SET_SPOOL_ID LANE=extruder1 SPOOL_ID=174", lines)

    def test_unknown_tool_and_missing_spoolman(self):
        self.assertTrue(self.run_macro("SPOOLMAN_SET_TOOL", TOOL=7, SPOOL=1)[0].startswith("_SPOOLMAN_PROBLEM"))
        self.spoolman = None
        self.assertTrue(self.run_macro("SPOOLMAN_SET_TOOL", SPOOL=1)[0].startswith("_SPOOLMAN_PROBLEM"))

    def test_done_activates_and_echoes(self):
        self.lanes["extruder1"]["spool_id"] = 174
        lines = self.run_macro("_SPOOLMAN_SET_TOOL_DONE", TOOL=1, SPOOL=174, ACTIVATE=1)
        self.assertEqual(self.calls, [("spoolman_set_active_spool", {"spool_id": 174})])
        self.assertEqual(lines, ['SPOOLMAN_ECHO MSG="Tool 1 has spool 174 (active)"'])

    def test_done_reports_rejected_spool(self):
        lines = self.run_macro("_SPOOLMAN_SET_TOOL_DONE", TOOL=1, SPOOL=999, ACTIVATE=1)
        self.assertEqual(self.calls, [])
        self.assertTrue(lines[0].startswith("_SPOOLMAN_PROBLEM"))

    def test_activate_tool(self):
        self.lanes["extruder2"]["spool_id"] = 42
        self.run_macro("SPOOLMAN_ACTIVATE_TOOL", TOOL=2)
        self.assertEqual(self.calls, [("spoolman_set_active_spool", {"spool_id": 42})])
        self.run_macro("SPOOLMAN_ACTIVATE_TOOL", TOOL=0)      # nothing assigned: clear
        self.assertEqual(self.calls[-1], ("spoolman_set_active_spool", {"spool_id": None}))

    def test_clear_tool(self):
        self.assertEqual(self.run_macro("SPOOLMAN_CLEAR_TOOL", TOOL=2), ["SPOOLMAN_SET_TOOL SPOOL=0 TOOL=2"])
        self.assertEqual(len(self.run_macro("SPOOLMAN_CLEAR_TOOL", ALL=1)), 4)

    def test_echo_follows_variable(self):
        self.run_macro("SPOOLMAN_ECHO", MSG="hi")
        self.assertEqual(self.info, ["Spoolman: hi"])
        self.vars["oc_spoolman_echo"] = 0
        self.run_macro("SPOOLMAN_ECHO", MSG="hidden")
        self.assertEqual(self.info, ["Spoolman: hi"])

    def test_echo_on_off_save_variable(self):
        self.assertIn("SAVE_VARIABLE VARIABLE=oc_spoolman_echo VALUE=1", self.run_macro("SPOOLMAN_ECHO_ON"))
        self.assertIn("SAVE_VARIABLE VARIABLE=oc_spoolman_echo VALUE=0", self.run_macro("SPOOLMAN_ECHO_OFF"))

    def test_problem_warns_while_printing(self):
        with self.assertRaises(RuntimeError):
            self.run_macro("_SPOOLMAN_PROBLEM", MSG="x")
        self.state = "printing"
        self.assertEqual(self.run_macro("_SPOOLMAN_PROBLEM", MSG="x"), ['RESPOND TYPE=error MSG="Spoolman: x"'])

    def test_tool_select_wrapper(self):
        self.assertEqual(self.cfg.get("gcode_macro C5_TOOL_SELECT", "rename_existing"),
                         "_OC_SPOOLMAN_TOOL_SELECT")
        self.assertEqual(self.run_macro("C5_TOOL_SELECT", T=2),
                         ["_OC_SPOOLMAN_TOOL_SELECT T=2", "_SPOOLMAN_TOOL_PICKED T=2"])

    def test_pickup_activates_tool_spool(self):
        self.lanes["extruder2"]["spool_id"] = 42
        lines = self.run_macro("_SPOOLMAN_TOOL_PICKED", T=2)
        self.assertEqual(self.calls, [("spoolman_set_active_spool", {"spool_id": 42})])
        self.assertEqual(lines, ['SPOOLMAN_ECHO MSG="T2 picked up: spool 42 active"'])

    def test_pickup_without_spool_clears_and_never_raises(self):
        self.assertTrue(self.run_macro("_SPOOLMAN_TOOL_PICKED", T=0)[0].startswith("SPOOLMAN_ECHO"))
        self.state = "printing"
        self.assertTrue(self.run_macro("_SPOOLMAN_TOOL_PICKED", T=0)[0].startswith("_SPOOLMAN_PROBLEM"))
        self.assertEqual(self.calls[-1], ("spoolman_set_active_spool", {"spool_id": None}))

    def test_pickup_does_nothing_without_spoolman(self):
        self.spoolman = None
        self.assertEqual(self.run_macro("_SPOOLMAN_TOOL_PICKED", T=1), [])
        self.assertEqual(self.calls, [])

    def test_status(self):
        self.lanes["extruder1"].update(spool_id=174, material="PETG", color="#FFD700")
        self.run_macro("SPOOLMAN_STATUS")
        self.assertIn("T1: spool 174, PETG #FFD700 (active tool)", self.info[0])
        self.assertIn("T0: no spool", self.info[0])


class ScriptTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.conf = os.path.join(self.dir, "moonraker.conf")
        with open(self.conf, "w") as f:
            f.write("[server]\nhost: 0.0.0.0\n\n#[spoolman]\n#server: http://x\n")

    def run_script(self, name, tunneled=""):
        env = dict(os.environ, OC_CONFIG_DIR=self.dir, OC_PLUGIN_DIR=str(ROOT), OC_TUNNELED=tunneled)
        return subprocess.run(["sh", str(ROOT / "scripts" / name)], env=env, cwd=str(ROOT),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)

    def read(self, name="moonraker.conf"):
        with open(os.path.join(self.dir, name)) as f:
            return f.read()

    def test_install_twice_then_uninstall(self):
        for _ in range(2):
            self.assertEqual(self.run_script("install.sh").returncode, 0)
        self.assertEqual(self.read().count("[include oc-spoolman.conf]"), 1)
        self.assertEqual(self.read("oc-spoolman.conf"), (ROOT / "moonraker" / "oc-spoolman.conf").read_text())
        self.assertEqual(self.run_script("uninstall.sh").returncode, 0)
        self.assertNotIn("[include oc-spoolman.conf]", self.read())
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "oc-spoolman.conf")))

    def test_install_refuses_tunneled_printer(self):
        before = self.read()
        r = self.run_script("install.sh", tunneled="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("SBC", r.stdout)
        self.assertEqual(self.read(), before)
        self.assertEqual(self.run_script("uninstall.sh", tunneled="1").returncode, 0)

    def test_install_keeps_edited_spoolman_conf(self):
        with open(os.path.join(self.dir, "oc-spoolman.conf"), "w") as f:
            f.write("[spoolman]\nserver: http://10.0.0.5:7912\n")
        self.run_script("install.sh")
        self.assertIn("10.0.0.5", self.read("oc-spoolman.conf"))

    def test_install_leaves_existing_spoolman_section(self):
        with open(self.conf, "a") as f:
            f.write("\n[spoolman]\nserver: http://10.0.0.5:7912\n")
        self.assertEqual(self.run_script("install.sh").returncode, 0)
        self.assertNotIn("[include oc-spoolman.conf]", self.read())
        self.assertFalse(os.path.exists(os.path.join(self.dir, "oc-spoolman.conf")))


if __name__ == "__main__":
    unittest.main()
