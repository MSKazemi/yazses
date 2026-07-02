"""Voice Case Transform (ADR-v2-087) + Auto-Pairing & Wrap (ADR-v2-088) — pure cores."""
from __future__ import annotations

from yazses.autopair.balance import balance_delimiters, detect_wrap_command, wrap
from yazses.casetransform.transform import detect_style_command, transform_case


# ---- case transform --------------------------------------------------------

def test_transform_programmer_cases():
    assert transform_case("my variable name", "snake") == "my_variable_name"
    assert transform_case("my variable name", "kebab") == "my-variable-name"
    assert transform_case("my variable name", "camel") == "myVariableName"
    assert transform_case("my variable name", "pascal") == "MyVariableName"
    assert transform_case("my variable name", "constant") == "MY_VARIABLE_NAME"


def test_transform_prose_cases_and_camel_split():
    assert transform_case("someHTTPValue", "snake") == "some_httpvalue"      # splits only at lower→UPPER
    assert transform_case("myVariableName", "kebab") == "my-variable-name"   # splits camelCase
    assert transform_case("hello world", "title") == "Hello World"
    assert transform_case("hello WORLD foo", "sentence") == "Hello world foo"
    assert transform_case("Mixed Case", "upper") == "MIXED CASE"
    assert transform_case("Mixed Case", "lower") == "mixed case"


def test_transform_empty():
    assert transform_case("", "snake") == ""
    assert transform_case("!!!", "camel") == "!!!"   # no tokens → unchanged
    assert transform_case("hi", "bogus") == "hi"     # unknown style → unchanged


def test_detect_style_command():
    assert detect_style_command("make this snake case") == "snake"
    assert detect_style_command("convert to camelCase") == "camel"
    assert detect_style_command("SHOUT this") == "upper"
    assert detect_style_command("just some words") is None


# ---- auto-pairing ----------------------------------------------------------

def test_balance_delimiters():
    assert balance_delimiters("foo(a, bar[b") == "foo(a, bar[b])"
    assert balance_delimiters('print("hi') == 'print("hi")'
    assert balance_delimiters("already()") == "already()"
    assert balance_delimiters('say("hi")') == 'say("hi")'    # balanced quote closes cleanly
    assert balance_delimiters("f('a[b')") == "f('a[b')"      # bracket inside a string ignored


def test_wrap():
    assert wrap("x", "parens") == "(x)"
    assert wrap("x", "double quotes") == '"x"'
    assert wrap("x", "curly braces") == "{x}"
    assert wrap("x", "nonsense") is None


def test_detect_wrap_command():
    assert detect_wrap_command("wrap this in parens") == "parens"
    assert detect_wrap_command("wrap it with backticks") == "backticks"
    assert detect_wrap_command("hello there") is None
    assert detect_wrap_command("wrap this in bananas") is None   # unknown pair name


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "casetransform" in slugs and "autopair" in slugs
    assert Config().casetransform.enabled is False and Config().autopair.enabled is False
