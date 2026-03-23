print("Loading dependencies (torch, transformers)...")
import torch
from transformers import Qwen3ForCausalLM, Qwen3ForSequenceClassification, AutoTokenizer
print("Dependencies loaded.")

def convert_model(model_path, save_path):
    
    # --- Step 1: Load the Causal LM and extract lm_head weights ---
    print(f"1. Loading Causal LM: {model_path}")
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    causal_lm = Qwen3ForCausalLM.from_pretrained(model_path)

    # The lm_head is the final linear layer that maps hidden states to vocabulary logits
    lm_head_weights = causal_lm.lm_head.weight
    print(f"   lm_head weight shape: {lm_head_weights.shape}") # (vocab_size, hidden_size)

    # --- Step 2: Get the token IDs for "yes" and "no" ---
    print("\n2. Finding token IDs for 'yes' and 'no'")
    yes_token_id = tokenizer.convert_tokens_to_ids("yes")
    no_token_id = tokenizer.convert_tokens_to_ids("no")
    print(f"   ID for 'yes': {yes_token_id}, ID for 'no': {no_token_id}")

    # --- Step 3: Create the classifier vector ---
    print("\n3. Creating the classifier vector from lm_head weights")
    # Extract the specific rows (weight vectors) for our target tokens
    yes_vector = lm_head_weights[yes_token_id]
    no_vector = lm_head_weights[no_token_id]

    # The new classifier is the difference between the 'yes' and 'no' vectors
    classifier_vector = yes_vector - no_vector
    print(f"   Shape of the new classifier vector: {classifier_vector.shape}")

    # --- Step 4: Load the model as a Sequence Classifier ---
    print(f"\n4. Loading Sequence Classification model with num_labels=1")
    # num_labels=1 is key for binary classification represented by a single logit
    seq_cls_model = Qwen3ForSequenceClassification.from_pretrained(
        model_path,
        num_labels=1,
        ignore_mismatched_sizes=True
    )

    # --- Step 5: Replace the classifier's weights ---
    print("\n5. Replacing the randomly initialized classifier weights")
    # The classification head in Qwen is named 'score'. It's a torch.nn.Linear layer.
    # Its weight matrix has shape (num_labels, hidden_size), which is (1, hidden_size) here.
    with torch.no_grad():
        # We need to add a dimension to our vector to match the (1, hidden_size) shape
        seq_cls_model.score.weight.copy_(classifier_vector.unsqueeze(0))
        # It's good practice to zero out the bias for a clean transfer
        if seq_cls_model.score.bias is not None:
            seq_cls_model.score.bias.zero_()

    print("   Classifier head replaced successfully.")


    # --- Verification: Prove that the logic works ---
    print("\n--- VERIFICATION ---")
    text = "Is this a good example?"
    inputs = tokenizer(text, return_tensors="pt")

    # A. Get logits from the original Causal LM
    with torch.no_grad():
        outputs_causal = causal_lm(**inputs)
        last_token_logits = outputs_causal.logits[0, -1, :]
        manual_logit_diff = last_token_logits[yes_token_id] - last_token_logits[no_token_id]

        # Compute probs (yes/no) and extract 'yes' prob
        concat_logits = torch.stack([last_token_logits[yes_token_id], last_token_logits[no_token_id]])
        causal_prob = torch.softmax(concat_logits, dim=-1)[0]

    # B. Get the single logit from our new Sequence Classification model
    with torch.no_grad():
        outputs_seq_cls = seq_cls_model(**inputs)
        # Shape is (1, 1), squeeze to scalar
        model_logit = outputs_seq_cls.logits.squeeze()
        # Compute 'yes' prob
        classification_prob = torch.sigmoid(model_logit)

    print(f"Input text: '{text}'")
    print(f"\nManual logit difference ('yes' - 'no'): {manual_logit_diff.item():.4f}")
    print(f"Sequence Classification model output:   {model_logit.item():.4f}")
    print(f"Are they almost identical? {torch.allclose(manual_logit_diff, model_logit)}")

    # Probs
    print(f"\nCausal prob (2 classes): {causal_prob.item():.4f}")
    print(f"Classification prob (1 class):   {classification_prob.item():.4f}")
    print(f"Are they almost identical? {torch.allclose(causal_prob, classification_prob)}")

    seq_cls_model.save_pretrained(save_path)
    tokenizer.save_pretrained(save_path)

    print(f"Save model to: {save_path}")

if __name__ == "__main__":

    model_path = "/root/autodl-fs/models/Qwen3-Reranker-0.6B"
    save_path = "/root/autodl-fs/models/Qwen3-Reranker-0.6B-seqcls-converted"
    print(f"Convert model from {model_path} to {save_path}")
    convert_model(model_path, save_path)
    print("Convert model successfully")