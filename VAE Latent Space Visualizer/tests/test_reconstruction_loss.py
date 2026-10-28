"""
Test Case 3: Reconstruction Loss

Verify:
- BCE reconstruction loss returns a finite value
- Reconstruction loss is non-negative
- Identical/near-identical predictions produce lower loss than poor predictions
- Reconstruction output has same shape as input
- Gradients propagate through reconstruction loss
"""

import pytest
import torch
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / 'src'))

from model import VAE
from losses import reconstruction_loss, vae_loss


class TestReconstructionLoss:
    """Test reconstruction loss properties."""
    
    @pytest.fixture
    def model(self):
        return VAE()
    
    @pytest.fixture
    def sample_input(self):
        return torch.rand(16, 1, 28, 28)
    
    def test_bce_loss_finite(self, model, sample_input):
        """Test BCE reconstruction loss returns finite value."""
        recon, mu, logvar = model(sample_input)
        loss = reconstruction_loss(recon, sample_input)
        
        assert torch.isfinite(loss), "Reconstruction loss is not finite"
    
    def test_bce_loss_non_negative(self, model, sample_input):
        """Test reconstruction loss is non-negative."""
        recon, _, _ = model(sample_input)
        loss = reconstruction_loss(recon, sample_input)
        
        assert loss.item() >= 0, f"Reconstruction loss negative: {loss.item()}"
    
    def test_identical_predictions_zero_loss(self):
        """Test identical predictions at extremes produce zero loss."""
        # BCE is zero only when pred=target=0 or pred=target=1
        x = torch.ones(10, 1, 28, 28)  # All ones
        loss = reconstruction_loss(x, x)
        
        assert torch.allclose(loss, torch.tensor(0.0), atol=1e-6), \
            f"Identical ones should give zero loss, got {loss.item()}"
        
        x = torch.zeros(10, 1, 28, 28)  # All zeros
        loss = reconstruction_loss(x, x)
        
        assert torch.allclose(loss, torch.tensor(0.0), atol=1e-6), \
            f"Identical zeros should give zero loss, got {loss.item()}"
    
    def test_near_identical_lower_loss(self):
        """Test near-identical predictions have lower loss than poor predictions."""
        x = torch.rand(10, 1, 28, 28)
        
        # Near-identical (small noise)
        near_identical = x + 0.01 * torch.randn_like(x)
        near_identical = torch.clamp(near_identical, 0, 1)
        
        # Poor prediction (random)
        poor = torch.rand_like(x)
        
        loss_near = reconstruction_loss(near_identical, x)
        loss_poor = reconstruction_loss(poor, x)
        
        assert loss_near < loss_poor, \
            f"Near-identical loss ({loss_near:.4f}) should be < poor loss ({loss_poor:.4f})"
    
    def test_output_shape_matches_input(self, model, sample_input):
        """Test reconstruction output has same shape as input."""
        recon, _, _ = model(sample_input)
        
        assert recon.shape == sample_input.shape, \
            f"Shape mismatch: recon {recon.shape} vs input {sample_input.shape}"
    
    def test_gradient_propagation(self, model, sample_input):
        """Test gradients propagate through reconstruction loss."""
        sample_input.requires_grad_(True)
        
        recon, mu, logvar = model(sample_input)
        loss = reconstruction_loss(recon, sample_input)
        loss.backward()
        
        assert sample_input.grad is not None, "No gradient wrt input"
        assert not torch.isnan(sample_input.grad).any(), "Input gradient has NaN"
        
        # Check model parameter gradients
        for name, param in model.named_parameters():
            assert param.grad is not None, f"No gradient for {name}"
            assert not torch.isnan(param.grad).any(), f"NaN gradient for {name}"
    
    def test_loss_reduction_modes(self, model, sample_input):
        """Test different reduction modes."""
        recon, _, _ = model(sample_input)
        
        loss_mean = reconstruction_loss(recon, sample_input, reduction='mean')
        loss_sum = reconstruction_loss(recon, sample_input, reduction='sum')
        loss_none = reconstruction_loss(recon, sample_input, reduction='none')
        
        assert loss_mean.shape == (), "Mean reduction should be scalar"
        assert loss_sum.shape == (), "Sum reduction should be scalar"
        assert loss_none.shape == (16, 784), "None reduction should be per-element"
        
        # Mean * num_elements = Sum
        assert torch.allclose(loss_mean * (16 * 784), loss_sum, rtol=1e-4)
    
    def test_per_sample_loss(self, model, sample_input):
        """Test per-sample loss computation."""
        from losses import compute_losses_per_sample
        
        recon, mu, logvar = model(sample_input)
        losses = compute_losses_per_sample(recon, sample_input, mu, logvar)
        
        assert losses['reconstruction'].shape == (16,), "Per-sample recon shape"
        assert losses['kl'].shape == (16,), "Per-sample KL shape"
        assert losses['total'].shape == (16,), "Per-sample total shape"
        
        assert (losses['reconstruction'] >= 0).all(), "Per-sample recon negative"
        assert (losses['kl'] >= -1e-6).all(), "Per-sample KL significantly negative"
    
    def test_numerical_stability(self):
        """Test loss handles edge cases (0 and 1 predictions)."""
        x = torch.ones(5, 1, 28, 28) * 0.5
        
        # Prediction exactly 0 or 1 (should be clamped internally)
        pred_zeros = torch.zeros_like(x)
        pred_ones = torch.ones_like(x)
        
        loss_zeros = reconstruction_loss(pred_zeros, x)
        loss_ones = reconstruction_loss(pred_ones, x)
        
        assert torch.isfinite(loss_zeros), "Loss with zeros not finite"
        assert torch.isfinite(loss_ones), "Loss with ones not finite"
        assert loss_zeros > 0, "Loss with zeros should be positive"
        assert loss_ones > 0, "Loss with ones should be positive"
    
    def test_batch_independence(self, model):
        """Test loss computed independently per batch."""
        x1 = torch.rand(8, 1, 28, 28)
        x2 = torch.rand(8, 1, 28, 28)
        
        recon1, _, _ = model(x1)
        recon2, _, _ = model(x2)
        
        loss1 = reconstruction_loss(recon1, x1)
        loss2 = reconstruction_loss(recon2, x2)
        
        # Combined batch
        x_combined = torch.cat([x1, x2])
        recon_combined = torch.cat([recon1, recon2])
        loss_combined = reconstruction_loss(recon_combined, x_combined)
        
        # Mean of separate should equal combined mean
        assert torch.allclose((loss1 + loss2) / 2, loss_combined, rtol=1e-4)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])