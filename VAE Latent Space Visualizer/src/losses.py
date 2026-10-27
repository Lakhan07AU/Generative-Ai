"""
VAE Loss Functions

Implements:
- Binary Cross-Entropy reconstruction loss
- KL Divergence between learned distribution and standard normal
- Total VAE loss with configurable beta
"""

import torch
import torch.nn.functional as F


def reconstruction_loss(recon_x: torch.Tensor, x: torch.Tensor, 
                        reduction: str = 'mean') -> torch.Tensor:
    """
    Compute Binary Cross-Entropy reconstruction loss.
    
    Args:
        recon_x: Reconstructed images of shape (batch_size, 1, 28, 28) or (batch_size, 784)
        x: Original images of same shape
        reduction: 'mean', 'sum', or 'none'
        
    Returns:
        BCE loss tensor
    """
    # Flatten if needed
    if recon_x.dim() == 4:
        recon_x = recon_x.view(recon_x.size(0), -1)
    if x.dim() == 4:
        x = x.view(x.size(0), -1)
    
    # Clamp for numerical stability
    recon_x = torch.clamp(recon_x, 1e-7, 1 - 1e-7)
    
    # BCE with logits would be more stable, but we use BCE since decoder has sigmoid
    loss = F.binary_cross_entropy(recon_x, x, reduction=reduction)
    
    return loss


def kl_divergence(mu: torch.Tensor, logvar: torch.Tensor,
                  reduction: str = 'mean') -> torch.Tensor:
    """
    Compute KL divergence between q(z|x) = N(mu, sigma^2) and p(z) = N(0, I).
    
    KL = -0.5 * sum(1 + logvar - mu^2 - exp(logvar))
    
    Args:
        mu: Latent mean of shape (batch_size, latent_dim)
        logvar: Latent log variance of shape (batch_size, latent_dim)
        reduction: 'mean', 'sum', or 'none'
        
    Returns:
        KL divergence tensor
    """
    # KL divergence for each sample in batch, summed over latent dimensions
    kl_per_sample = -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp(), dim=1)
    
    if reduction == 'mean':
        return kl_per_sample.mean()
    elif reduction == 'sum':
        return kl_per_sample.sum()
    else:  # 'none'
        return kl_per_sample


def vae_loss(recon_x: torch.Tensor, x: torch.Tensor, 
             mu: torch.Tensor, logvar: torch.Tensor,
             beta: float = 1.0,
             reduction: str = 'mean') -> dict:
    """
    Compute total VAE loss = Reconstruction Loss + beta * KL Divergence.
    
    Args:
        recon_x: Reconstructed images
        x: Original images
        mu: Latent mean
        logvar: Latent log variance
        beta: Weight for KL divergence term (default 1.0)
        reduction: 'mean', 'sum', or 'none'
        
    Returns:
        Dictionary with 'reconstruction', 'kl', 'total' losses
    """
    recon_loss = reconstruction_loss(recon_x, x, reduction=reduction)
    kl_loss = kl_divergence(mu, logvar, reduction=reduction)
    total_loss = recon_loss + beta * kl_loss
    
    return {
        'reconstruction': recon_loss,
        'kl': kl_loss,
        'total': total_loss
    }


def compute_losses_per_sample(recon_x: torch.Tensor, x: torch.Tensor,
                               mu: torch.Tensor, logvar: torch.Tensor,
                               beta: float = 1.0) -> dict:
    """
    Compute losses for each sample individually (no batch reduction).
    
    Useful for per-sample analysis and visualization.
    
    Args:
        recon_x: Reconstructed images
        x: Original images
        mu: Latent mean
        logvar: Latent log variance
        beta: KL weight
        
    Returns:
        Dictionary with per-sample losses
    """
    if recon_x.dim() == 4:
        recon_x = recon_x.view(recon_x.size(0), -1)
    if x.dim() == 4:
        x = x.view(x.size(0), -1)
    
    # Per-sample reconstruction loss (sum over pixels)
    recon_per_sample = F.binary_cross_entropy(recon_x, x, reduction='none').sum(dim=1)
    
    # Per-sample KL divergence (sum over latent dims)
    kl_per_sample = -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp(), dim=1)
    
    total_per_sample = recon_per_sample + beta * kl_per_sample
    
    return {
        'reconstruction': recon_per_sample,
        'kl': kl_per_sample,
        'total': total_per_sample
    }


if __name__ == "__main__":
    # Quick test
    batch_size = 16
    x = torch.rand(batch_size, 1, 28, 28)
    recon_x = torch.rand(batch_size, 1, 28, 28)
    mu = torch.randn(batch_size, 2)
    logvar = torch.randn(batch_size, 2)
    
    losses = vae_loss(recon_x, x, mu, logvar, beta=1.0)
    print(f"Reconstruction loss: {losses['reconstruction'].item():.4f}")
    print(f"KL divergence: {losses['kl'].item():.4f}")
    print(f"Total loss: {losses['total'].item():.4f}")
    
    # Test per-sample
    per_sample = compute_losses_per_sample(recon_x, x, mu, logvar)
    print(f"Per-sample recon shape: {per_sample['reconstruction'].shape}")
    print(f"Per-sample KL shape: {per_sample['kl'].shape}")
    print("Loss functions working correctly!")