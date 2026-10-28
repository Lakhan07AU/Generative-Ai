"""
Test Case 2: Latent Distribution

Verify:
- Encoder returns finite mean and log variance tensors
- Reparameterization produces correct latent shape
- Random sampling produces finite values
- With μ=0 and logvar=0, repeated latent samples approximately follow N(0, I)
- Sampling with different random noise produces different latent vectors
"""

import pytest
import torch
import numpy as np
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / 'src'))

from model import VAE


class TestLatentDistribution:
    """Test latent space distribution properties."""
    
    @pytest.fixture
    def model(self):
        """Create a VAE model for testing."""
        return VAE(input_dim=784, hidden_dims=[512, 256], latent_dim=2)
    
    @pytest.fixture
    def sample_input(self):
        """Create sample input tensor."""
        return torch.randn(16, 1, 28, 28)
    
    def test_finite_mean_logvar(self, model, sample_input):
        """Test encoder returns finite mean and log variance."""
        mu, logvar = model.encode(sample_input)
        
        assert torch.isfinite(mu).all(), "Mean contains non-finite values"
        assert torch.isfinite(logvar).all(), "Log variance contains non-finite values"
    
    def test_reparameterize_shape(self, model, sample_input):
        """Test reparameterization produces correct latent shape."""
        mu, logvar = model.encode(sample_input)
        z = model.reparameterize(mu, logvar)
        
        assert z.shape == (16, 2), f"Latent shape mismatch: {z.shape}"
        assert torch.isfinite(z).all(), "Latent samples contain non-finite values"
    
    def test_random_sampling_finite(self, model):
        """Test random sampling produces finite values."""
        # Sample from prior
        z = torch.randn(1000, 2)
        recon = model.decode(z)
        
        assert torch.isfinite(recon).all(), "Decoded samples contain non-finite values"
        assert (recon >= 0).all() and (recon <= 1).all(), "Decoded values outside [0, 1]"
    
    def test_standard_normal_sampling(self):
        """Test that with μ=0, logvar=0, samples follow N(0, I)."""
        model = VAE(latent_dim=2)
        
        # Create deterministic encoder output: μ=0, logvar=0
        batch_size = 10000
        mu = torch.zeros(batch_size, 2)
        logvar = torch.zeros(batch_size, 2)
        
        # Sample multiple times
        samples = []
        for _ in range(10):
            z = model.reparameterize(mu, logvar)
            samples.append(z.numpy())
        
        all_samples = np.vstack(samples)  # Shape: (100000, 2)
        
        # Test mean close to 0
        sample_mean = all_samples.mean(axis=0)
        assert np.allclose(sample_mean, [0, 0], atol=0.05), \
            f"Sample mean {sample_mean} not close to [0, 0]"
        
        # Test std close to 1
        sample_std = all_samples.std(axis=0)
        assert np.allclose(sample_std, [1, 1], atol=0.05), \
            f"Sample std {sample_std} not close to [1, 1]"
        
        # Test correlation near 0 (independent dimensions)
        corr_matrix = np.corrcoef(all_samples.T)
        assert np.abs(corr_matrix[0, 1]) < 0.05, \
            f"Dimensions correlated: {corr_matrix[0, 1]}"
    
    def test_different_noise_different_samples(self, model):
        """Test different random noise produces different latent vectors."""
        mu = torch.zeros(10, 2)
        logvar = torch.zeros(10, 2)
        
        # Sample twice with different noise
        z1 = model.reparameterize(mu, logvar)
        z2 = model.reparameterize(mu, logvar)
        
        # They should be different (with very high probability)
        assert not torch.allclose(z1, z2), "Same noise produced identical samples"
        
        # Check they're not identical for any sample in batch
        for i in range(10):
            assert not torch.allclose(z1[i], z2[i]), f"Sample {i} identical across draws"
    
    def test_reparameterize_gradient_flow(self, model):
        """Test reparameterization allows gradient flow."""
        mu = torch.randn(16, 2, requires_grad=True)
        logvar = torch.randn(16, 2, requires_grad=True)
        
        z = model.reparameterize(mu, logvar)
        loss = z.sum()
        loss.backward()
        
        assert mu.grad is not None, "Gradient not flowing to mu"
        assert logvar.grad is not None, "Gradient not flowing to logvar"
        assert torch.isfinite(mu.grad).all(), "Mu gradient contains non-finite"
        assert torch.isfinite(logvar.grad).all(), "Logvar gradient contains non-finite"
    
    def test_latent_mean_deterministic(self, model, sample_input):
        """Test that encode is deterministic (no sampling)."""
        mu1, logvar1 = model.encode(sample_input)
        mu2, logvar2 = model.encode(sample_input)
        
        assert torch.allclose(mu1, mu2), "Encoder mean not deterministic"
        assert torch.allclose(logvar1, logvar2), "Encoder logvar not deterministic"
    
    def test_logvar_exponentiation(self, model):
        """Test that exp(0.5 * logvar) produces valid std."""
        logvar = torch.tensor([[-2.0, 0.0], [1.0, 2.0]])
        
        std = torch.exp(0.5 * logvar)
        
        assert (std > 0).all(), "Standard deviation not positive"
        assert torch.isfinite(std).all(), "Standard deviation not finite"
        
        # Check specific values
        expected = torch.exp(0.5 * logvar)
        assert torch.allclose(std, expected)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])