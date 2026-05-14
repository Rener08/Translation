from app.services.transcript_cleaner import (
    CleanResult,
    clean_transcript,
    _remove_fillers,
    _remove_markers,
    _remove_duplicate_sentences,
)


def test_remove_fillers():
    text = "嗯，我觉得啊这个产品呃还是不错的"
    result, count = _remove_fillers(text)
    assert "嗯" not in result
    assert "啊" not in result
    assert "呃" not in result
    assert count >= 3
    assert "产品" in result
    assert "不错" in result


def test_remove_markers():
    text = "大家好[音乐]今天我们来聊聊[掌声]AI的发展"
    result, count = _remove_markers(text)
    assert "[音乐]" not in result
    assert "[掌声]" not in result
    assert count == 2
    assert "大家好" in result
    assert "AI" in result


def test_remove_duplicates():
    text = "句子A。句子A。句子B。"
    result, count = _remove_duplicate_sentences(text)
    assert count == 1
    assert result == "句子A。句子B。"


def test_empty_input():
    result = clean_transcript("")
    assert result.cleaned_text == ""
    assert result.removed_filler_count == 0
    assert result.removed_marker_count == 0
    assert result.removed_duplicate_count == 0


def test_none_input():
    result = clean_transcript(None)
    assert result.cleaned_text == ""


def test_no_noise():
    text = "这是一个干净的文本，没有口水词和标记。"
    result = clean_transcript(text)
    assert result.cleaned_text == text
    assert result.removed_filler_count == 0
    assert result.removed_marker_count == 0
    assert result.removed_duplicate_count == 0


def test_extra_fillers():
    text = "话说这个功能确实不错"
    result, count = _remove_fillers(text, extra=("话说",))
    assert "话说" not in result
    assert count >= 1


def test_clean_result_counts():
    text = "嗯[音乐]好的。好的。"
    result = clean_transcript(text)
    assert result.removed_filler_count >= 1
    assert result.removed_marker_count == 1
    assert result.removed_duplicate_count == 1
    assert "好的" in result.cleaned_text


def test_combined_cleaning():
    text = "嗯[音乐][掌声]好的。好的。还不错。"
    result = clean_transcript(text)
    assert result.removed_filler_count >= 1
    assert result.removed_marker_count == 2
    assert result.removed_duplicate_count >= 1
    assert "好的" in result.cleaned_text
    assert "不错" in result.cleaned_text


def test_selective_cleaning():
    text = "嗯[音乐]好的"
    result = clean_transcript(text, remove_fillers=False, remove_markers=True)
    assert "嗯" in result.cleaned_text
    assert "[音乐]" not in result.cleaned_text
    assert result.removed_filler_count == 0
    assert result.removed_marker_count == 1
