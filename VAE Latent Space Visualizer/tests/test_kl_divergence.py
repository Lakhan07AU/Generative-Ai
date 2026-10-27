"""
Test Case 4: KL Divergence

Verify:
- KL divergence returns a finite value
- KL divergence is non-negative within floating-point tolerance
- For μ=0 and logvar=0, KL divergence is approximately zero
- Moving mean away from zero increases KL divergence when variance fixed at one
- KL divergence supports gradient backpropagation
"""

import pytest
import torch
import numpy as np
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / 'src'))

from model import VAE
from losses import kl_divergence, vae_loss


class TestKLDivergence:
    """Test KL divergence properties."""
    
    @pytest.fixture
    def model(self):
        return VAE()
    
    @pytest.fixture
    def sample_input(self):
        # Use torch.rand for valid BCE targets in [0, 1]
        return torch.rand(16, 1, 28, 28)
    
    def test_kl_finite(self, model, sample_input):
        """Test KL divergence returns finite value."""
        _, mu, logvar = model(sample_input)
        kl = kl_divergence(mu, logvar)
        
        assert torch.isfinite(kl), "KL divergence is not finite"
    
    def test_kl_non_negative(self, model, sample_input):
        """Test KL divergence is non-negative (within numerical tolerance)."""
        _, mu, logvar = model(sample_input)
        kl = kl_divergence(mu, logvar)
        
        # Allow small negative due to floating point
        assert kl.item() >= -1e-5, f"KL divergence significantly negative: {kl.item()}"
    
    def test_kl_zero_for_standard_normal(self):
        """Test KL ≈ 0 for μ=0, logvar=0 (standard normal)."""
        batch_size = 1000
        mu = torch.zeros(batch_size, 2)
        logvar = torch.zeros(batch_size, 2)
        
        kl = kl_divergence(mu, logvar)
        
        assert torch.allclose(kl, torch.tensor(0.0), atol=1e-4), \
            f"KL for standard normal should be ~0, got {kl.item()}"
    
    def test_kl_increases_with_mean_shift(self):
        """Test KL increases when mean moves away from zero (fixed variance=1)."""
        batch_size = 100
        logvar = torch.zeros(batch_size, 2)  # variance = 1
        
        # μ = 0
        mu_zero = torch.zeros(batch_size, 2)
        kl_zero = kl_divergence(mu_zero, logvar)
        
        # μ = 1
        mu_one = torch.ones(batch_size, 2)
        kl_one = kl_divergence(mu_one, logvar)
        
        # μ = 2
        mu_two = torch.full((batch_size, 2), 2.0)
        kl_two = kl_divergence(mu_two, logvar)
        
        assert kl_zero < kl_one < kl_two, \
            f"KL should increase with mean shift: {kl_zero:.4f} < {kl_one:.4f} < {kl_two:.4f}"
    
    def test_kl_increases_with_variance_change(self):
        """Test KL increases when variance deviates from 1 (fixed mean=0)."""
        batch_size = 100
        mu = torch.zeros(batch_size, 2)
        
        # logvar = 0 (variance = 1)
        logvar_one = torch.zeros(batch_size, 2)
        kl_one = kl_divergence(mu, logvar_one)
        
        # logvar = 1 (variance = e ≈ 2.718)
        logvar_e = torch.ones(batch_size, 2)
        kl_e = kl_divergence(mu, logvar_e)
        
        # logvar = -1 (variance = 1/e ≈ 0.368)
        logvar_inv_e = torch.full((batch_size, 2), -1.0)
        kl_inv_e = kl_divergence(mu, logvar_inv_e)
        
        # Both deviations from 1 should increase KL
        assert kl_one < kl_e, f"KL should increase with variance > 1: {kl_one:.4f} < {kl_e:.4f}"
        assert kl_one < kl_inv_e, f"KL should increase with variance < 1: {kl_one:.4f} < {kl_inv_e:.4f}"
    
    def test_kl_gradient_flow(self):
        """Test KL divergence supports gradient backpropagation."""
        mu = torch.randn(16, 2, requires_grad=True)
        logvar = torch.randn(16, 2, requires_grad=True)
        
        kl = kl_divergence(mu, logvar)
        kl.backward()
        
        assert mu.grad is not None, "Gradient not flowing to mu"
        assert logvar.grad is not None, "Gradient not flowing to logvar"
        assert torch.isfinite(mu.grad).all(), "Mu gradient has non-finite"
        assert torch.isfinite(logvar.grad).all(), "Logvar gradient has non-finite"
    
    def test_kl_per_sample(self):
        """Test per-sample KL computation."""
        from losses import compute_losses_per_sample
        
        batch_size = 10
        mu = torch.randn(batch_size, 2)
        logvar = torch.randn(batch_size, 2)
        recon = torch.rand(batch_size, 1, 28, 28)
        x = torch.rand(batch_size, 1, 28, 28)
        
        losses = compute_losses_per_sample(recon, x, mu, logvar)
        
        assert losses['kl'].shape == (batch_size,), "Per-sample KL shape"
        assert (losses['kl'] >= -1e-5).all(), "Per-sample KL significantly negative"
    
    def test_kl_reduction_modes(self):
        """Test different reduction modes."""
        batch_size = 10
        mu = torch.randn(batch_size, 2)
        logvar = torch.randn(batch_size, 2)
        
        kl_mean = kl_divergence(mu, logvar, reduction='mean')
        kl_sum = kl_divergence(mu, logvar, reduction='sum')
        kl_none = kl_divergence(mu, logvar, reduction='none')
        
        assert kl_mean.shape == (), "Mean reduction should be scalar"
        assert kl_sum.shape == (), "Sum reduction should be scalar"
        assert kl_none.shape == (batch_size,), "None reduction should be per-sample"
        
        assert torch.allclose(kl_mean * batch_size, kl_sum, rtol=1e-4)
    
    def test_kl_formula_correctness(self):
        """Test KL formula matches analytical calculation."""
        # For N(μ, σ²) vs N(0, 1):
        # KL = 0.5 * (σ² + μ² - 1 - log(σ²))
        #    = -0.5 * (1 + log(σ²) - μ² - σ²)
        
        mu = torch.tensor([[1.0, -1.0], [2.0, 0.0]])
        logvar = torch.tensor([[0.0, 1.0], [-1.0, 2.0]])  # σ² = exp(logvar)
        
        kl = kl_divergence(mu, logvar, reduction='none')
        
        # Manual calculation
        var = logvar.exp()
        kl_manual = 0.5 * (var + mu**2 - 1 - logvar)
        kl_manual = kl_manual.sum(dim=1)
        
        assert torch.allclose(kl, kl_manual, rtol=1e-4), \
            f"KL formula mismatch: {kl} vs {kl_manual}"
    
    def test_kl_with_vae_loss(self, model, sample_input):
        """Test KL integrates correctly with VAE loss."""
        recon, mu, logvar = model(sample_input)
        losses = vae_loss(recon, sample_input, mu, logvar, beta=1.0)
        
        assert 'reconstruction' in losses
        assert 'kl' in losses
        assert 'total' in losses
        
        assert torch.isfinite(losses['kl']), "KL in VAE loss not finite"
        assert torch.isfinite(losses['total']), "Total loss not finite"
        
        # Total = recon + beta * kl
        expected_total = losses['reconstruction'] + 1.0 * losses['kl']
        assert torch.allclose(losses['total'], expected_total, rtol=1e-4)
    
    def test_kl_beta_scaling(self, model, sample_input):
        """Test beta scaling in VAE loss."""
        _, mu, logvar = model(sample_input)
        
        kl_beta1 = kl_divergence(mu, logvar)
        kl_beta2 = kl_divergence(mu, logvar)
        
        # In VAE loss
        losses1 = vae_loss(model(sample_input)[0], sample_input, mu, logvar, beta=1.0)
        losses2 = vae_loss(model(sample_input)[0], sample_input, mu, logvar, beta=2.0)
        
        assert torch.allclose(losses2['kl'], losses1['kl']), "KL shouldn't change with beta"
        assert losses2['total'] > losses1['total'], "Total loss should increase with beta"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])