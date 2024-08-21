# -*- coding: utf-8 -*-
"""Transformer.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1yRt-UTwm6_1S0dvy6ceP_q6Q7fUZKQ6f
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import math

# InputEmbedding class creates an embedding layer that scales the output embeddings by the square root of the embedding dimension (d_model).
# This scaling helps stabilize gradients during training.
class InputEmbedding(nn.Module):
  def __init__(self, d_model:int, vocab_size:int):
    super().__init__()
    self.d_model = d_model
    self.vocab_size = vocab_size
    self.embedding = nn.Embedding(vocab_size, d_model)
  def forward(self, x):
    return self.embedding(x) * math.sqrt(self.d_model)

# PositionalEncoding class generates and applies sinusoidal positional encodings to the input embeddings.
# This encoding helps the model capture the order of tokens in a sequence, which is crucial for sequential data processing.
# The dropout layer is used to prevent overfitting by randomly zeroing some of the elements in the input tensor.
class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, seq_len: int, dropout: float) -> None:
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        positional_encoding = torch.zeros(seq_len, d_model)
        position = torch.arange(0, seq_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        positional_encoding[:, 0::2] = torch.sin(position * div_term)
        positional_encoding[:, 1::2] = torch.cos(position * div_term)
        positional_encoding = positional_encoding.unsqueeze(0)
        self.register_buffer('positional_encoding', positional_encoding)

    def forward(self, x):
        x = x + self.positional_encoding[:, :x.shape[1], :].requires_grad_(False)
        return self.dropout(x)

# LayerNormalization class applies layer normalization to the input tensor.
# Layer normalization stabilizes the learning process by normalizing the input across the features of a single layer,
# ensuring that the outputs have zero mean and unit variance. This is particularly useful in deep networks to prevent
# internal covariate shift.
class LayerNormalization(nn.Module):
    def __init__(self, eps: float = 10**-6) -> None:
        super().__init__()
        self.eps = eps
        self.alpha = nn.Parameter(torch.ones(1))
        self.bias = nn.Parameter(torch.zeros(1))

    def forward(self, x):
        mean = x.mean(dim=-1, keepdim=True)
        std = x.std(dim=-1, keepdim=True)
        return self.alpha * (x - mean) / (std + self.eps) + self.bias

# FeedForwardBlock class implements a two-layer feedforward neural network with ReLU activation and dropout.
# This block is typically used in transformer models to process the output of the attention mechanism.
# The first linear layer expands the dimensionality, the ReLU activation adds non-linearity,
# dropout is applied for regularization, and the second linear layer projects the output back to the original dimension.
class FeedForwardBlock(nn.Module):
    def __init__(self, d_model: int, d_ff: int, dropout: float) -> None:
        super().__init__()
        self.linear_1 = nn.Linear(d_model, d_ff)
        self.dropout = nn.Dropout(dropout)
        self.linear_2 = nn.Linear(d_ff, d_model)

    def forward(self, x):
        return self.linear_2(self.dropout(F.relu(self.linear_1(x))))

# MultiHeadAttentionBlock class implements the multi-head attention mechanism used in transformer models.
# Multi-head attention allows the model to focus on different parts of the input sequence simultaneously,
# capturing various relationships between tokens. The input is split into multiple heads, each head performs
# scaled dot-product attention, and the results are concatenated and projected back to the original dimension.
class MultiHeadAttentionBlock(nn.Module):
    def __init__(self, d_model: int, h: int, dropout: float) -> None:
        super().__init__()
        self.d_model = d_model
        self.h = h
        assert d_model % h == 0, "d_model is not divisible by h"
        self.d_k = d_model // h
        self.w_q = nn.Linear(d_model, d_model)
        self.w_k = nn.Linear(d_model, d_model)
        self.w_v = nn.Linear(d_model, d_model)
        self.w_o = nn.Linear(d_model, d_model)
        self.dropout = nn.Dropout(dropout)

    def attention(self, query, key, value, mask, dropout):
        d_k = query.shape[-1]
        attention_scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(d_k)
        if mask is not None:
            attention_scores = attention_scores.masked_fill(mask == 0, -1e9)
        attention_scores = attention_scores.softmax(dim=-1)
        if dropout is not None:
            attention_scores = dropout(attention_scores)
        return torch.matmul(attention_scores, value)

    def forward(self, q, k, v, mask):
        query = self.w_q(q)
        key = self.w_k(k)
        value = self.w_v(v)
        query = query.view(query.shape[0], query.shape[1], self.h, self.d_k).transpose(1, 2)
        key = key.view(key.shape[0], key.shape[1], self.h, self.d_k).transpose(1, 2)
        value = value.view(value.shape[0], value.shape[1], self.h, self.d_k).transpose(1, 2)
        x = self.attention(query, key, value, mask, self.dropout)
        x = x.transpose(1, 2).contiguous().reshape(x.shape[0], -1, self.h * self.d_k)
        return self.w_o(x)

# Residual class implements a residual connection with layer normalization and dropout.
# Residual connections help in training deep networks by mitigating the vanishing gradient problem,
# allowing gradients to flow through the network more effectively.
# The input is first normalized, passed through a sublayer, followed by dropout,
# and finally added back to the original input.
class Residual(nn.Module):
    def __init__(self, dropout: float) -> None:
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        self.norm = LayerNormalization()

    def forward(self, x, sublayer):
        return x + self.dropout(sublayer(self.norm(x)))

# EncoderBlock class represents a single block in the transformer encoder.
# It consists of a multi-head self-attention mechanism, followed by a feedforward network,
# with residual connections and layer normalization applied after each sublayer.
# This structure allows the encoder to capture complex relationships in the input sequence while maintaining stable gradients.
class EncoderBlock(nn.Module):
    def __init__(self, self_attention_block: MultiHeadAttentionBlock, feed_forward_block: FeedForwardBlock, dropout: float) -> None:
        super().__init__()
        self.self_attention_block = self_attention_block
        self.feed_forward_block = feed_forward_block
        self.residual_connections = nn.ModuleList([Residual(dropout) for _ in range(2)])

    def forward(self, x, src_mask):
        x = self.residual_connections[0](x, lambda x: self.self_attention_block(x, x, x, src_mask))
        x = self.residual_connections[1](x, self.feed_forward_block)
        return x

# Encoder class stacks multiple encoder blocks to form the transformer encoder.
# The input passes through each encoder block in sequence, allowing the model to build a rich representation of the input.
# Finally, layer normalization is applied to the output of the last encoder block for stability.
class Encoder(nn.Module):
    def __init__(self, layers: nn.ModuleList) -> None:
        super().__init__()
        self.layers = layers
        self.norm = LayerNormalization()

    def forward(self, x, mask):
        for layer in self.layers:
            x = layer(x, mask)
        return self.norm(x)

vocab_size = 5  # vocabulary size example
d_model = 512
seq_len = 5  # sequence length example

# test example
vocab = {word: idx for idx, word in enumerate(["this", "is", "an", "example", "sentence"])}
sentence = ["this", "is", "an", "example", "sentence"]

# convert the sentence into indices
input_indices = [vocab[word] for word in sentence]

input_tensor = torch.LongTensor(input_indices).unsqueeze(0)  # (1, seq_len)

# create embedding and positional encoding
embedding = InputEmbedding(d_model=d_model, vocab_size=vocab_size)
pos_encoding = PositionalEncoding(d_model=d_model, seq_len=seq_len, dropout=0.1)

# create encoder layers
num_layers = 6
dropout = 0.1
attention_heads = 8
d_ff = 2048

layers = nn.ModuleList([
    EncoderBlock(
        MultiHeadAttentionBlock(d_model=d_model, h=attention_heads, dropout=dropout),
        FeedForwardBlock(d_model=d_model, d_ff=d_ff, dropout=dropout),
        dropout=dropout
    ) for _ in range(num_layers)
])

encoder = Encoder(layers=layers)

# feed forward
x = embedding(input_tensor)
x = pos_encoding(x)
output = encoder(x, None)

print(output)
print(output.shape)