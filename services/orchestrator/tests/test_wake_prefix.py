from wake import detect_wake_prefix


def test_hey_samantha_with_command():
    prefix, remainder = detect_wake_prefix("Hey Samantha, what's the weather?")
    assert prefix == "hey samantha"
    assert remainder == "what's the weather?"


def test_bare_samantha_with_command():
    prefix, remainder = detect_wake_prefix("Samantha tell me a joke")
    assert prefix == "samantha"
    assert remainder == "tell me a joke"


def test_okay_samantha():
    prefix, remainder = detect_wake_prefix("Okay Samantha, look at me")
    assert prefix == "okay samantha"
    assert remainder == "look at me"


def test_ok_samantha():
    prefix, remainder = detect_wake_prefix("ok samantha what time is it")
    assert prefix == "ok samantha"
    assert remainder == "what time is it"


def test_hi_samantha():
    prefix, remainder = detect_wake_prefix("Hi Samantha!")
    assert prefix == "hi samantha"
    assert remainder == ""


def test_wake_only_no_command():
    prefix, remainder = detect_wake_prefix("Samantha")
    assert prefix == "samantha"
    assert remainder == ""


def test_no_match():
    prefix, remainder = detect_wake_prefix("Hey what's up")
    assert prefix is None
    assert remainder == "Hey what's up"


def test_mid_sentence_samantha_no_match():
    prefix, remainder = detect_wake_prefix("Tell samantha about the meeting")
    assert prefix is None


def test_case_insensitive():
    prefix, remainder = detect_wake_prefix("HEY SAMANTHA how are you")
    assert prefix == "hey samantha"
    assert remainder == "how are you"


def test_trailing_punctuation_stripped():
    prefix, remainder = detect_wake_prefix("Hey Samantha, ... what's up?")
    assert prefix == "hey samantha"
    assert remainder == "what's up?"


def test_empty_string():
    prefix, remainder = detect_wake_prefix("")
    assert prefix is None
    assert remainder == ""


def test_whitespace_only():
    prefix, remainder = detect_wake_prefix("   ")
    assert prefix is None
    assert remainder == ""
