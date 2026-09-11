"""Structural scorers operate on the model reply, not on mocks of themselves."""

from bancada.models import MachineCheck
from bancada.scorers import extract_code, run_checks


def test_extract_code_takes_fenced_python_block() -> None:
    text = "claro:\n```python\ndef reverse(s):\n    return s[::-1]\n```\npronto"
    assert "def reverse" in extract_code(text)
    assert "return s[::-1]" in extract_code(text)


def test_extract_code_preserves_leading_indent() -> None:
    text = "```python\n    for x in xs:\n        return True\n    return False\n```"
    lines = extract_code(text).splitlines()
    assert lines[0].startswith("    for")
    assert lines[1].startswith("        return True")
    assert lines[2].startswith("    return False")


def test_python_test_passes_when_extracted_code_satisfies_assert() -> None:
    reply = "```python\ndef reverse(s):\n    return s[::-1]\n```"
    checks = [MachineCheck(type="python_test", source='assert reverse("ab") == "ba"')]
    results = run_checks(reply, checks, tool_calls=None)
    assert results[0].ok is True


def test_python_test_fails_when_function_is_wrong() -> None:
    reply = "```python\ndef reverse(s):\n    return s\n```"
    checks = [MachineCheck(type="python_test", source='assert reverse("ab") == "ba"')]
    results = run_checks(reply, checks, tool_calls=None)
    assert results[0].ok is False


def test_python_test_fails_when_code_times_out() -> None:
    reply = "```python\nwhile True:\n    pass\n```"
    checks = [MachineCheck(type="python_test", source="assert True")]
    results = run_checks(reply, checks, tool_calls=None)
    assert results[0].ok is False
    assert "timeout" in results[0].reason.lower()


def test_python_test_prepends_setup_for_body_only_completion() -> None:
    reply = "```python\nreturn True\n```"
    checks = [
        MachineCheck(
            type="python_test",
            setup="def foo():\n",
            source="assert foo() is True",
        )
    ]
    results = run_checks(reply, checks, tool_calls=None)
    assert results[0].ok is True
    without_setup = [MachineCheck(type="python_test", source="assert foo() is True")]
    assert run_checks(reply, without_setup, tool_calls=None)[0].ok is False


def test_python_test_does_not_double_prepend_when_signature_already_present() -> None:
    reply = "```python\ndef foo():\n    return True\n```"
    checks = [
        MachineCheck(
            type="python_test",
            setup="def foo():\n",
            source="assert foo() is True",
        )
    ]
    results = run_checks(reply, checks, tool_calls=None)
    assert results[0].ok is True


def test_python_test_keeps_relative_indent_of_multiline_body() -> None:
    reply = "```python\n    for x in xs:\n        return True\n    return False\n```"
    checks = [
        MachineCheck(
            type="python_test",
            setup="def foo(xs):\n",
            source="assert foo([]) is False\nassert foo([1]) is True",
        )
    ]
    results = run_checks(reply, checks, tool_calls=None)
    assert results[0].ok is True


def test_python_test_keeps_comment_then_def_at_module_level() -> None:
    reply = "```python\n# helper\ndef foo():\n    return True\n```"
    checks = [
        MachineCheck(
            type="python_test",
            setup="def foo():\n    return False\n",
            source="assert foo() is True",
        )
    ]
    results = run_checks(reply, checks, tool_calls=None)
    assert results[0].ok is True


def test_python_test_prepends_missing_typing_import_for_full_def() -> None:
    reply = (
        "```python\n"
        "def foo(xs: List[int]) -> bool:\n"
        "    return isinstance(xs, List) and not xs\n"
        "```"
    )
    checks = [
        MachineCheck(
            type="python_test",
            setup=(
                "from typing import List\n\n"
                "def foo(xs: List[int]) -> bool:\n"
                '    """doc"""\n'
            ),
            source="assert foo([]) is True",
        )
    ]
    results = run_checks(reply, checks, tool_calls=None)
    assert results[0].ok is True
    without_setup = [
        MachineCheck(type="python_test", source="assert foo([]) is True")
    ]
    assert run_checks(reply, without_setup, tool_calls=None)[0].ok is False


def test_wikilink_allowlist_rejects_unknown_targets() -> None:
    reply = "Ver [[Ponteiros]] e [[Marte]]."
    checks = [MachineCheck(type="wikilink_allowlist", allowed=["Ponteiros", "AEDS1"])]
    results = run_checks(reply, checks, tool_calls=None)
    assert results[0].ok is False
    assert "Marte" in results[0].reason


def test_wikilink_allowlist_passes_subset() -> None:
    reply = "Ver [[Ponteiros]]."
    checks = [MachineCheck(type="wikilink_allowlist", allowed=["Ponteiros", "AEDS1"])]
    assert run_checks(reply, checks, tool_calls=None)[0].ok is True


def test_tool_name_matches_openai_tool_calls() -> None:
    checks = [MachineCheck(type="tool_name", expected="cron")]
    tool_calls = [{"function": {"name": "cron", "arguments": "{}"}}]
    assert run_checks("", checks, tool_calls=tool_calls)[0].ok is True


def test_tool_name_null_passes_when_no_tool_called() -> None:
    checks = [MachineCheck(type="tool_name", expected=None)]
    assert run_checks("resposta direta", checks, tool_calls=None)[0].ok is True
    assert run_checks("resposta", checks, tool_calls=[])[0].ok is True


def test_tool_name_null_fails_when_a_tool_is_called() -> None:
    checks = [MachineCheck(type="tool_name", expected=None)]
    tool_calls = [{"function": {"name": "exec", "arguments": "{}"}}]
    assert run_checks("", checks, tool_calls=tool_calls)[0].ok is False


def test_not_empty_fails_on_whitespace() -> None:
    checks = [MachineCheck(type="not_empty")]
    assert run_checks("   \n", checks, tool_calls=None)[0].ok is False
    assert run_checks("ok", checks, tool_calls=None)[0].ok is True
