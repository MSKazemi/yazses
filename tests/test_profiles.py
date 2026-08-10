from yazses.config import ProfilesConfig
from yazses.postprocess.profiles import resolve_profile

def test_resolve_profile_match():
    config = ProfilesConfig(app={"*code*": "formal", "*slack*": "casual", "*term*": "verbatim"})
    
    prof = resolve_profile("VSCode", config)
    assert prof.tone == "formal"
    
    prof = resolve_profile("slack", config)
    assert prof.tone == "casual"
    
    prof = resolve_profile("gnome-terminal", config)
    assert prof.tone == "verbatim"

def test_resolve_profile_unknown_app():
    config = ProfilesConfig(app={"*code*": "formal", "*slack*": "casual"})
    
    prof = resolve_profile("chrome", config)
    assert prof.tone == ""

def test_resolve_profile_empty_config():
    config = ProfilesConfig()
    
    prof = resolve_profile("chrome", config)
    assert prof.tone == ""
