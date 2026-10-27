"""
Visualization Utilities for VAE Latent Space Visualizer

Generates plots for:
- Original vs reconstructed images
- 2D latent space scatter plot
- Training loss curves
- Generated digit grid from latent space
"""

import torch
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for saving
from typing import Optional, List, Tuple
import os
import sys


def plot_reconstruction_comparison(original: torch.Tensor, 
                                    reconstructed: torch.Tensor,
                                    labels: Optional[torch.Tensor] = None,
                                    num_samples: int = 10,
                                    save_path: Optional[str] = None) -> plt.Figure:
    """
    Plot original vs reconstructed images side by side.
    
    Args:
        original: Original images (batch_size, 1, 28, 28)
        reconstructed: Reconstructed images (batch_size, 1, 28, 28)
        labels: Optional labels for each image
        num_samples: Number of samples to display
        save_path: Optional path to save the figure
        
    Returns:
        Matplotlib figure
    """
    num_samples = min(num_samples, original.size(0))
    
    fig, axes = plt.subplots(2, num_samples, figsize=(2 * num_samples, 4))
    
    for i in range(num_samples):
        # Original
        orig_img = original[i].squeeze().cpu().numpy()
        axes[0, i].imshow(orig_img, cmap='gray', vmin=0, vmax=1)
        axes[0, i].axis('off')
        if labels is not None:
            axes[0, i].set_title(f'Original: {labels[i].item()}')
        else:
            axes[0, i].set_title('Original')
        
        # Reconstructed
        recon_img = reconstructed[i].squeeze().cpu().numpy()
        axes[1, i].imshow(recon_img, cmap='gray', vmin=0, vmax=1)
        axes[1, i].axis('off')
        axes[1, i].set_title('Reconstructed')
    
    plt.tight_layout()
    
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    return fig


def plot_latent_space(encoder, test_loader, device: torch.device,
                       num_samples: int = 2000,
                       save_path: Optional[str] = None) -> plt.Figure:
    """
    Plot 2D latent space scatter plot colored by digit labels.
    
    Args:
        encoder: VAE encoder (or full VAE model)
        test_loader: DataLoader for test set
        device: Torch device
        num_samples: Maximum number of samples to encode
        save_path: Optional path to save the figure
        
    Returns:
        Matplotlib figure
    """
    encoder.eval()
    
    latent_means = []
    labels_list = []
    
    with torch.no_grad():
        for images, labels in test_loader:
            images = images.to(device)
            mu, _ = encoder.encode(images)
            latent_means.append(mu.cpu().numpy())
            labels_list.append(labels.numpy())
            
            if len(latent_means) * images.size(0) >= num_samples:
                break
    
    latent_means = np.vstack(latent_means)[:num_samples]
    labels_list = np.hstack(labels_list)[:num_samples]
    
    fig, ax = plt.subplots(figsize=(10, 8))
    
    scatter = ax.scatter(
        latent_means[:, 0], latent_means[:, 1],
        c=labels_list, cmap='tab10', alpha=0.6, s=10
    )
    
    ax.set_xlabel('Latent Dimension 1', fontsize=12)
    ax.set_ylabel('Latent Dimension 2', fontsize=12)
    ax.set_title('VAE Latent Space (MNIST Test Set)', fontsize=14)
    
    # Add legend
    legend1 = ax.legend(*scatter.legend_elements(num=10),
                        title="Digits", loc="upper right")
    ax.add_artist(legend1)
    
    plt.colorbar(scatter, ax=ax, label='Digit Label')
    plt.tight_layout()
    
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    return fig


def plot_training_history(history: dict, save_path: Optional[str] = None) -> plt.Figure:
    """
    Plot training loss curves.
    
    Args:
        history: Dictionary with keys 'recon_loss', 'kl_loss', 'total_loss'
        save_path: Optional path to save the figure
        
    Returns:
        Matplotlib figure
    """
    epochs = range(1, len(history['recon_loss']) + 1)
    
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    
    # Reconstruction loss
    axes[0].plot(epochs, history['recon_loss'], 'b-', label='Reconstruction')
    axes[0].set_xlabel('Epoch')
    axes[0].set_ylabel('Loss')
    axes[0].set_title('Reconstruction Loss (BCE)')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    
    # KL divergence
    axes[1].plot(epochs, history['kl_loss'], 'r-', label='KL Divergence')
    axes[1].set_xlabel('Epoch')
    axes[1].set_ylabel('Loss')
    axes[1].set_title('KL Divergence')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    
    # Total loss
    axes[2].plot(epochs, history['total_loss'], 'g-', label='Total')
    axes[2].set_xlabel('Epoch')
    axes[2].set_ylabel('Loss')
    axes[2].set_title('Total VAE Loss')
    axes[2].legend()
    axes[2].grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    return fig


def plot_generated_grid(decoder, device: torch.device,
                         grid_size: int = 15,
                         latent_range: float = 3.0,
                         save_path: Optional[str] = None) -> plt.Figure:
    """
    Generate a grid of images by decoding points across the 2D latent space.
    
    Args:
        decoder: VAE decoder
        device: Torch device
        grid_size: Number of points per dimension
        latent_range: Range of latent space to cover (-range to +range)
        save_path: Optional path to save the figure
        
    Returns:
        Matplotlib figure
    """
    decoder.eval()
    
    # Create grid of latent points
    x = np.linspace(-latent_range, latent_range, grid_size)
    y = np.linspace(-latent_range, latent_range, grid_size)
    
    fig, axes = plt.subplots(grid_size, grid_size, figsize=(grid_size, grid_size))
    
    with torch.no_grad():
        for i, yi in enumerate(reversed(y)):  # Reverse y for correct orientation
            for j, xi in enumerate(x):
                z = torch.tensor([[xi, yi]], dtype=torch.float32).to(device)
                generated = decoder(z).cpu()
                # Reshape explicitly to (28, 28) for imshow
                generated = generated.view(28, 28).numpy()
                
                axes[i, j].imshow(generated, cmap='gray', vmin=0, vmax=1)
                axes[i, j].axis('off')
    
    plt.suptitle(f'Generated Digits from Latent Space Grid ({grid_size}x{grid_size})', 
                 fontsize=14)
    plt.tight_layout()
    
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    return fig


def plot_latent_traversal(decoder, device: torch.device,
                           fixed_dim: int = 0,
                           num_steps: int = 10,
                           latent_range: float = 3.0,
                           save_path: Optional[str] = None) -> plt.Figure:
    """
    Plot latent traversal: vary one latent dimension while keeping other fixed.
    
    Args:
        decoder: VAE decoder
        device: Torch device
        fixed_dim: Which dimension to keep fixed (0 or 1)
        num_steps: Number of steps
        latent_range: Range to traverse
        save_path: Optional path to save
        
    Returns:
        Matplotlib figure
    """
    decoder.eval()
    
    fig, axes = plt.subplots(1, num_steps, figsize=(2 * num_steps, 2))
    
    with torch.no_grad():
        for i in range(num_steps):
            val = np.linspace(-latent_range, latent_range, num_steps)[i]
            z = torch.zeros(1, 2).to(device)
            z[0, fixed_dim] = val
            z[0, 1 - fixed_dim] = 0.0
            
            generated = decoder(z).cpu().view(28, 28).numpy()
            axes[i].imshow(generated, cmap='gray', vmin=0, vmax=1)
            axes[i].axis('off')
            axes[i].set_title(f'z{fixed_dim+1}={val:.1f}')
    
    plt.suptitle(f'Latent Traversal: Dimension {fixed_dim+1}', fontsize=14)
    plt.tight_layout()
    
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    return fig


def save_all_visualizations(model, train_loader, test_loader, device,
                             history: dict, output_dir: str = 'outputs'):
    """
    Generate and save all standard visualizations.
    
    Args:
        model: Trained VAE model
        train_loader: Training data loader
        test_loader: Test data loader
        device: Torch device
        history: Training history dictionary
        output_dir: Directory to save plots
    """
    os.makedirs(output_dir, exist_ok=True)
    
    model.eval()
    
    # Get a batch of test images for reconstruction
    test_images, test_labels = next(iter(test_loader))
    test_images = test_images.to(device)
    test_labels = test_labels.to(device)
    
    with torch.no_grad():
        recon, _, _ = model(test_images)
    
    # 1. Reconstruction comparison
    plot_reconstruction_comparison(
        test_images.cpu(), recon.cpu(), test_labels.cpu(),
        num_samples=10,
        save_path=os.path.join(output_dir, 'reconstruction_comparison.png')
    )
    
    # 2. Latent space scatter
    plot_latent_space(
        model, test_loader, device,
        num_samples=2000,
        save_path=os.path.join(output_dir, 'latent_space_scatter.png')
    )
    
    # 3. Training history
    if history:
        plot_training_history(
            history,
            save_path=os.path.join(output_dir, 'training_history.png')
        )
    
    # 4. Generated grid
    plot_generated_grid(
        model.decoder, device,
        grid_size=15,
        save_path=os.path.join(output_dir, 'generated_grid.png')
    )
    
    # 5. Latent traversals
    plot_latent_traversal(
        model.decoder, device,
        fixed_dim=0,
        save_path=os.path.join(output_dir, 'latent_traversal_dim1.png')
    )
    plot_latent_traversal(
        model.decoder, device,
        fixed_dim=1,
        save_path=os.path.join(output_dir, 'latent_traversal_dim2.png')
    )
    
    plt.close('all')
    print(f"All visualizations saved to {output_dir}/")


if __name__ == "__main__":
    # Quick test with dummy data
    print("Visualization module loaded successfully!")