# tests/test_model.py

import pytest
from src.main import model, tokenizer

@pytest.mark.parametrize('input_text, expected_output', [
    ('Hello, how are you?', [101, 2023, 2003, 2005, 4998, 102]),
    ('This is a test.', [101, 2023, 2003, 2005, 4998, 102])
])
def test_model(input_text, expected_output):
    inputs = tokenizer(input_text, return_tensors='pt')
    inputs = inputs.to('cpu')

    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits
        predictions = torch.argmax(logits, dim=-1)

    assert predictions.tolist() == expected_output