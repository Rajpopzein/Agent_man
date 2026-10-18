import torch
from transformers import BertModel, BertConfig

# Load the pre-trained model configuration
cfg = BertConfig.from_pretrained('bert-base-uncased')

# Create a new model with the same configuration but without the classification head
model = BertModel(cfg)

# Load the weights of the encoder part
model.load_state_dict(torch.load('path_to_your_weights.pth', map_location=torch.device('cpu'), weights_only=False, map_location=torch.device('cpu')), strict=False)

# Initialize the classification head if needed
# For example, if you want to use a simple classification head:
# model.cls = torch.nn.Linear(cfg.hidden_size, num_labels)

# Move the model to the desired device (e.g., GPU)
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model.to(device)

# Example usage
input_ids = torch.tensor([[101, 2023, 2003, 2005, 4998, 102]])  # Example input
input_ids = input_ids.to(device)

with torch.no_grad():
    outputs = model(input_ids)
    logits = outputs.logits
    predictions = torch.argmax(logits, dim=-1)

print(predictions)