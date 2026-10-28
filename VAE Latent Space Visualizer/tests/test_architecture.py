"""
Test Case 1: Encoder-Decoder Architecture

Verify:
- Encoder accepts input shape (batch_size, 1, 28, 28)
- Mean output shape (batch_size, 2)
- Log variance output shape (batch_size, 2)
- Reparameterized latent vector shape (batch_size, 2)
- Decoder output shape (batch_size, 1, 28, 28)
- Reconstructed pixel values in [0, 1]
- Forward and backward pass produces valid gradients
"""

import pytest
import torch
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / 'src'))

from model import VAE


class TestArchitecture:
    """Test VAE encoder-decoder architecture."""
    
    @pytest.fixture
    def model(self):
        """Create a VAE model for testing."""
        return VAE(input_dim=784, hidden_dims=[512, 256], latent_dim=2)
    
    @pytest.fixture
    def sample_input(self):
        """Create sample input tensor."""
        return torch.randn(16, 1, 28, 28)
    
    def test_encoder_input_shape(self, model, sample_input):
        """Test encoder accepts correct input shape."""
        mu, logvar = model.encode(sample_input)
        assert mu.shape == (16, 2), f"Expected mu shape (16, 2), got {mu.shape}"
        assert logvar.shape == (16, 2), f"Expected logvar shape (16, 2), got {logvar.shape}"
    
    def test_encoder_output_shapes(self, model, sample_input):
        """Test encoder outputs have correct shapes."""
        mu, logvar = model.encode(sample_input)
        
        # Mean shape
        assert mu.shape == (16, 2), f"Mean shape mismatch: {mu.shape}"
        
        # Log variance shape
        assert logvar.shape == (16, 2), f"Logvar shape mismatch: {logvar.shape}"
    
    def test_reparameterize_shape(self, model, sample_input):
        """Test reparameterization produces correct latent shape."""
        mu, logvar = model.encode(sample_input)
        z = model.reparameterize(mu, logvar)
        
        assert z.shape == (16, 2), f"Latent shape mismatch: {z.shape}"
    
    def test_decoder_output_shape(self, model, sample_input):
        """Test decoder output has correct shape."""
        mu, logvar = model.encode(sample_input)
        z = model.reparameterize(mu, logvar)
        recon = model.decode(z)
        
        assert recon.shape == (16, 1, 28, 28), f"Decoder output shape mismatch: {recon.shape}"
    
    def test_forward_pass_shapes(self, model, sample_input):
        """Test complete forward pass produces correct shapes."""
        recon, mu, logvar = model(sample_input)
        
        assert recon.shape == (16, 1, 28, 28), f"Recon shape mismatch: {recon.shape}"
        assert mu.shape == (16, 2), f"Mu shape mismatch: {mu.shape}"
        assert logvar.shape == (16, 2), f"Logvar shape mismatch: {logvar.shape}"
    
    def test_reconstructed_pixel_range(self, model, sample_input):
        """Test reconstructed pixel values are in [0, 1]."""
        recon, _, _ = model(sample_input)
        
        assert recon.min() >= 0.0, f"Min pixel value {recon.min()} < 0"
        assert recon.max() <= 1.0, f"Max pixel value {recon.max()} > 1"
    
    def test_gradient_flow(self, model, sample_input):
        """Test forward and backward pass produces valid gradients."""
        model.train()
        sample_input.requires_grad_(True)
        
        recon, mu, logvar = model(sample_input)
        
        # Simple loss to trigger backward
        loss = recon.mean() + mu.mean() + logvar.mean()
        loss.backward()
        
        # Check gradients exist
        assert sample_input.grad is not None, "Input gradient is None"
        assert not torch.isnan(sample_input.grad).any(), "Input gradient contains NaN"
        
        # Check model parameter gradients
        for name, param in model.named_parameters():
            assert param.grad is not None, f"Parameter {name} has no gradient"
            assert not torch.isnan(param.grad).any(), f"Parameter {name} gradient contains NaN"
    
    def test_flattened_input(self, model):
        """Test encoder works with flattened input (batch_size, 784)."""
        flat_input = torch.randn(16, 784)
        mu, logvar = model.encode(flat_input)
        
        assert mu.shape == (16, 2)
        assert logvar.shape == (16, 2)
    
    def test_different_batch_sizes(self, model):
        """Test model works with different batch sizes."""
        for batch_size in [1, 4, 32, 64]:
            x = torch.randn(batch_size, 1, 28, 28)
            recon, mu, logvar = model(x)
            
            assert recon.shape == (batch_size, 1, 28, 28)
            assert mu.shape == (batch_size, 2)
            assert logvar.shape == (batch_size, 2)
    
    def test_latent_dimension_configurable(self):
        """Test latent dimension can be configured."""
        for latent_dim in [2, 10, 20, 50]:
            model = VAE(latent_dim=latent_dim)
            x = torch.randn(8, 1, 28, 28)
            recon, mu, logvar = model(x)
            
            assert mu.shape == (8, latent_dim)
            assert logvar.shape == (8, latent_dim)
            assert recon.shape == (8, 1, 28, 28)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])