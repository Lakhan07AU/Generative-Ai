"""
VAE Model Architecture for MNIST

Implements a fully connected Variational Autoencoder with:
- Encoder: 784 -> 512 -> 256 -> (mu, logvar) for latent_dim=2
- Reparameterization trick for differentiable sampling
- Decoder: 2 -> 256 -> 512 -> 784 with sigmoid output
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class VAE(nn.Module):
    """
    Variational Autoencoder for MNIST digits.
    
    Architecture:
    Encoder:
        Input: 784 (flattened 28x28)
        Linear(784, 512) -> ReLU
        Linear(512, 256) -> ReLU
        Linear(256, latent_dim) -> mu
        Linear(256, latent_dim) -> logvar
    
    Decoder:
        Input: latent_dim (2)
        Linear(2, 256) -> ReLU
        Linear(256, 512) -> ReLU
        Linear(512, 784) -> Sigmoid
        Output: 784 (reconstructed 28x28)
    """
    
    def __init__(self, input_dim: int = 784, hidden_dims: list = None, 
                 latent_dim: int = 2):
        super(VAE, self).__init__()
        
        if hidden_dims is None:
            hidden_dims = [512, 256]
        
        self.input_dim = input_dim
        self.latent_dim = latent_dim
        self.hidden_dims = hidden_dims
        
        # Encoder
        encoder_layers = []
        prev_dim = input_dim
        for h_dim in hidden_dims:
            encoder_layers.append(nn.Linear(prev_dim, h_dim))
            encoder_layers.append(nn.ReLU())
            prev_dim = h_dim
        self.encoder = nn.Sequential(*encoder_layers)
        
        # Latent mean and log variance
        self.fc_mu = nn.Linear(hidden_dims[-1], latent_dim)
        self.fc_logvar = nn.Linear(hidden_dims[-1], latent_dim)
        
        # Decoder
        decoder_layers = []
        prev_dim = latent_dim
        for h_dim in reversed(hidden_dims):
            decoder_layers.append(nn.Linear(prev_dim, h_dim))
            decoder_layers.append(nn.ReLU())
            prev_dim = h_dim
        decoder_layers.append(nn.Linear(prev_dim, input_dim))
        decoder_layers.append(nn.Sigmoid())
        self.decoder = nn.Sequential(*decoder_layers)
    
    def encode(self, x: torch.Tensor) -> tuple:
        """
        Encode input to latent distribution parameters.
        
        Args:
            x: Input tensor of shape (batch_size, 1, 28, 28) or (batch_size, 784)
            
        Returns:
            mu: Latent mean of shape (batch_size, latent_dim)
            logvar: Latent log variance of shape (batch_size, latent_dim)
        """
        # Flatten if needed
        if x.dim() == 4:
            x = x.view(x.size(0), -1)
        
        h = self.encoder(x)
        mu = self.fc_mu(h)
        logvar = self.fc_logvar(h)
        return mu, logvar
    
    def reparameterize(self, mu: torch.Tensor, logvar: torch.Tensor) -> torch.Tensor:
        """
        Reparameterization trick: z = mu + sigma * epsilon
        
        Args:
            mu: Latent mean of shape (batch_size, latent_dim)
            logvar: Latent log variance of shape (batch_size, latent_dim)
            
        Returns:
            z: Sampled latent vector of shape (batch_size, latent_dim)
        """
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std
    
    def decode(self, z: torch.Tensor) -> torch.Tensor:
        """
        Decode latent vector to reconstructed image.
        
        Args:
            z: Latent vector of shape (batch_size, latent_dim)
            
        Returns:
            recon_x: Reconstructed image of shape (batch_size, 1, 28, 28)
        """
        recon = self.decoder(z)
        return recon.view(-1, 1, 28, 28)
    
    def forward(self, x: torch.Tensor) -> tuple:
        """
        Forward pass through the VAE.
        
        Args:
            x: Input tensor of shape (batch_size, 1, 28, 28)
            
        Returns:
            recon_x: Reconstructed image
            mu: Latent mean
            logvar: Latent log variance
        """
        mu, logvar = self.encode(x)
        z = self.reparameterize(mu, logvar)
        recon_x = self.decode(z)
        return recon_x, mu, logvar
    
    def get_num_parameters(self) -> int:
        """Return total number of trainable parameters."""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
    
    def get_architecture_summary(self) -> dict:
        """Return a summary of the model architecture."""
        return {
            'input_dim': self.input_dim,
            'latent_dim': self.latent_dim,
            'hidden_dims': self.hidden_dims,
            'num_parameters': self.get_num_parameters(),
            'encoder_layers': [
                f"Linear({self.input_dim}, {self.hidden_dims[0]})",
                "ReLU",
                f"Linear({self.hidden_dims[0]}, {self.hidden_dims[1]})",
                "ReLU",
                f"Linear({self.hidden_dims[1]}, {self.latent_dim}) -> mu",
                f"Linear({self.hidden_dims[1]}, {self.latent_dim}) -> logvar"
            ],
            'decoder_layers': [
                f"Linear({self.latent_dim}, {self.hidden_dims[1]})",
                "ReLU",
                f"Linear({self.hidden_dims[1]}, {self.hidden_dims[0]})",
                "ReLU",
                f"Linear({self.hidden_dims[0]}, {self.input_dim})",
                "Sigmoid"
            ]
        }


def create_vae(config: dict = None) -> VAE:
    """
    Factory function to create VAE from configuration.
    
    Args:
        config: Dictionary with keys: input_dim, hidden_dims, latent_dim
        
    Returns:
        VAE model instance
    """
    if config is None:
        config = {}
    
    return VAE(
        input_dim=config.get('input_dim', 784),
        hidden_dims=config.get('hidden_dims', [512, 256]),
        latent_dim=config.get('latent_dim', 2)
    )


if __name__ == "__main__":
    # Quick test
    model = VAE()
    print(f"Model created with {model.get_num_parameters():,} parameters")
    
    # Test forward pass
    x = torch.randn(16, 1, 28, 28)
    recon, mu, logvar = model(x)
    print(f"Input shape: {x.shape}")
    print(f"Reconstructed shape: {recon.shape}")
    print(f"Mu shape: {mu.shape}")
    print(f"Logvar shape: {logvar.shape}")
    print("Forward pass successful!")