from app.tools.capabilities import detect_missing_capability


def test_detects_missing_internet_capability():
    assert (
        detect_missing_capability(
            "I don't have access to the internet from this environment."
        )
        == "internet"
    )


def test_does_not_misclassify_normal_internet_text():
    assert (
        detect_missing_capability(
            "I used the internet documentation to verify the API."
        )
        is None
    )
