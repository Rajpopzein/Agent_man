# src/main.py

import torch
from transformers import AutoModel, AutoTokenizer

model_name = 'bert-base-uncased'
model = AutoModel.from_pretrained(model_name)
tokenizer = AutoTokenizer.from_pretrained(model_name)

if __name__ == '__main__':
    input_text = 'Hello, how are you?'
    inputs = tokenizer(input_text, return_tensors='pt')
    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits
        predictions = torch.argmax(logits, dim=-1)
        print(predictions.tolist())