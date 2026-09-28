"""The shared-namespace wrapper must behave the same under the session's split globals/locals."""

import unittest

from script_executor import clamp_timeout, wrap_shared_namespace

USER_SCRIPT = '''
def helper():
    return 41

def main():
    return helper() + 1

text = u"caf\\u00e9 'single' \\"double\\" back\\\\slash"
result = {"success": True, "value": main(), "text": text, "sees_session": session is not None}
'''


class SharedNamespaceTests(unittest.TestCase):
    def run_like_session(self, script):
        # PERSISTENT_SESSION.execute_script uses exec(code, globals_dict, local_vars).
        globals_dict, local_vars = {"session": object()}, {}
        exec(wrap_shared_namespace(script), globals_dict, local_vars)
        return local_vars["result"]

    def test_functions_can_call_each_other(self):
        result = self.run_like_session(USER_SCRIPT)
        self.assertEqual(result["value"], 42)
        self.assertTrue(result["sees_session"])

    def test_quotes_backslashes_and_unicode_survive(self):
        self.assertEqual(self.run_like_session(USER_SCRIPT)["text"], "café 'single' \"double\" back\\slash")

    def test_missing_result_defaults_to_success(self):
        self.assertTrue(self.run_like_session("x = 1\n")["success"])

    def test_the_bug_it_fixes(self):
        with self.assertRaises(NameError):
            exec(USER_SCRIPT, {"session": object()}, {})

    def test_clamp_timeout(self):
        self.assertEqual(clamp_timeout(None, 60, 300), 60)
        self.assertEqual(clamp_timeout("junk", 60, 300), 60)
        self.assertEqual(clamp_timeout(900, 60, 300), 300.0)
        self.assertEqual(clamp_timeout(0, 60, 300), 1.0)


if __name__ == "__main__":
    unittest.main()
