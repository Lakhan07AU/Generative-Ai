"""
VAE Evaluation Script for MNIST

Loads a trained VAE model and evaluates it on the test set.
Generates reconstruction examples and latent space visualizations.
"""

import os
import json
import argparse
import torch
import numpy as np
import matplotlib.pyplot as plt

from src.model import VAE, create_vae
from src.dataset import get_data_loaders, get_test_subset_indices
from src.losses import vae_loss, compute_losses_per_sample
from src.visualization import (plot_reconstruction_comparison, 
                                plot_latent_space,
                                plot_generated_grid,
                                plot_latent_traversal)


def get_device() -> torch.device:
    """Get the best available device."""
    if torch.cuda.is_available():
        return torch.device('cuda')
    return torch.device('cpu')


def load_model(checkpoint_path: str, device: torch.device) -> tuple:
    """
    Load model from checkpoint.
    
    Returns:
        model: Loaded VAE model
        config: Model configuration
        history: Training history (if available)
    """
    if not os.path.exists(checkpoint_path):
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")
    
    checkpoint = torch.load(checkpoint_path, map_location=device)
    
    config = checkpoint.get('config', {})
    model = create_vae(config).to(device)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.eval()
    
    history = checkpoint.get('history', {})
    
    print(f"Model loaded from {checkpoint_path}")
    print(f"Architecture: {config}")
    print(f"Epochs trained: {checkpoint.get('epoch', 'unknown')}")
    
    return model, config, history


def evaluate_model(model: VAE, test_loader, device: torch.device,
                   beta: float = 1.0) -> dict:
    """
    Evaluate model on full test set.
    
    Returns:
        Dictionary with average losses
    """
    model.eval()
    
    total_recon = 0.0
    total_kl = 0.0
    total_loss = 0.0
    num_batches = 0
    
    print("Evaluating on test set...")
    
    with torch.no_grad():
        for images, _ in test_loader:
            images = images.to(device)
            
            recon, mu, logvar = model(images)
            losses = vae_loss(recon, images, mu, logvar, beta=beta)
            
            total_recon += losses['reconstruction'].item()
            total_kl += losses['kl'].item()
            total_loss += losses['total'].item()
            num_batches += 1
    
    avg_recon = total_recon / num_batches
    avg_kl = total_kl / num_batches
    avg_total = total_loss / num_batches
    
    return {
        'reconstruction_loss': avg_recon,
        'kl_divergence': avg_kl,
        'total_loss': avg_total,
        'num_batches': num_batches
    }


def evaluate_per_sample(model: VAE, test_loader, device: torch.device,
                        beta: float = 1.0, max_samples: int = 1000) -> dict:
    """
    Compute per-sample losses for detailed analysis.
    """
    model.eval()
    
    all_recon = []
    all_kl = []
    all_total = []
    all_labels = []
    
    with torch.no_grad():
        for images, labels in test_loader:
            images = images.to(device)
            
            recon, mu, logvar = model(images)
            losses = compute_losses_per_sample(recon, images, mu, logvar, beta)
            
            all_recon.append(losses['reconstruction'].cpu().numpy())
            all_kl.append(losses['kl'].cpu().numpy())
            all_total.append(losses['total'].cpu().numpy())
            all_labels.append(labels.numpy())
            
            if len(np.concatenate(all_recon)) >= max_samples:
                break
    
    return {
        'reconstruction': np.concatenate(all_recon)[:max_samples],
        'kl': np.concatenate(all_kl)[:max_samples],
        'total': np.concatenate(all_total)[:max_samples],
        'labels': np.concatenate(all_labels)[:max_samples]
    }


def generate_visualizations(model: VAE, test_loader, device: torch.device,
                            output_dir: str = 'outputs', num_samples: int = 2000):
    """
    Generate and save evaluation visualizations.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    model.eval()
    
    # Get a batch for reconstruction comparison
    test_images, test_labels = next(iter(test_loader))
    test_images = test_images.to(device)
    
    with torch.no_grad():
        recon, _, _ = model(test_images)
    
    # 1. Reconstruction comparison
    plot_reconstruction_comparison(
        test_images.cpu(), recon.cpu(), test_labels.cpu(),
        num_samples=10,
        save_path=os.path.join(output_dir, 'eval_reconstruction_comparison.png')
    )
    print(f"Saved reconstruction comparison")
    
    # 2. Latent space scatter
    plot_latent_space(
        model, test_loader, device,
        num_samples=num_samples,
        save_path=os.path.join(output_dir, 'eval_latent_space_scatter.png')
    )
    print(f"Saved latent space scatter plot")
    
    # 3. Generated grid
    plot_generated_grid(
        model.decoder, device,
        grid_size=15,
        save_path=os.path.join(output_dir, 'eval_generated_grid.png')
    )
    print(f"Saved generated grid")
    
    # 4. Latent traversals
    plot_latent_traversal(
        model.decoder, device,
        fixed_dim=0,
        save_path=os.path.join(output_dir, 'eval_latent_traversal_dim1.png')
    )
    plot_latent_traversal(
        model.decoder, device,
        fixed_dim=1,
        save_path=os.path.join(output_dir, 'eval_latent_traversal_dim2.png')
    )
    print(f"Saved latent traversals")
    
    plt.close('all')


def print_architecture_summary(model: VAE):
    """Print model architecture summary."""
    summary = model.get_architecture_summary()
    
    print("\n" + "=" * 50)
    print("MODEL ARCHITECTURE SUMMARY")
    print("=" * 50)
    print(f"Input Dimension: {summary['input_dim']}")
    print(f"Latent Dimension: {summary['latent_dim']}")
    print(f"Hidden Dimensions: {summary['hidden_dims']}")
    print(f"Total Parameters: {summary['num_parameters']:,}")
    
    print("\nEncoder:")
    for layer in summary['encoder_layers']:
        print(f"  {layer}")
    
    print("\nDecoder:")
    for layer in summary['decoder_layers']:
        print(f"  {layer}")


def save_evaluation_results(results: dict, output_path: str):
    """Save evaluation results to JSON."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Convert numpy types to Python types for JSON serialization
    serializable = {}
    for key, value in results.items():
        if isinstance(value, (np.floating, np.integer)):
            serializable[key] = float(value)
        elif isinstance(value, np.ndarray):
            serializable[key] = value.tolist()
        else:
            serializable[key] = value
    
    with open(output_path, 'w') as f:
        json.dump(serializable, f, indent=2)
    print(f"Evaluation results saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Evaluate VAE on MNIST')
    parser.add_argument('--checkpoint', type=str, default='models/vae_mnist.pth',
                        help='Path to model checkpoint')
    parser.add_argument('--batch-size', type=int, default=128, help='Batch size')
    parser.add_argument('--beta', type=float, default=1.0, help='KL weight')
    parser.add_argument('--output-dir', type=str, default='outputs',
                        help='Output directory for visualizations')
    parser.add_argument('--results-path', type=str, default='outputs/evaluation_results.json',
                        help='Path to save evaluation results')
    parser.add_argument('--num-samples', type=int, default=2000,
                        help='Number of samples for latent space plot')
    
    args = parser.parse_args()
    
    device = get_device()
    print(f"Using device: {device}")
    
    # Load model
    try:
        model, config, history = load_model(args.checkpoint, device)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Please train the model first using: python train.py")
        return
    
    # Print architecture
    print_architecture_summary(model)
    
    # Get data loader
    _, test_loader = get_data_loaders(batch_size=args.batch_size)
    
    # Evaluate
    print("\n" + "=" * 50)
    print("EVALUATION RESULTS")
    print("=" * 50)
    
    avg_losses = evaluate_model(model, test_loader, device, beta=args.beta)
    
    print(f"Test Reconstruction Loss (BCE): {avg_losses['reconstruction_loss']:.6f}")
    print(f"Test KL Divergence:             {avg_losses['kl_divergence']:.6f}")
    print(f"Test Total VAE Loss:            {avg_losses['total_loss']:.6f}")
    print(f"Number of test batches:         {avg_losses['num_batches']}")
    
    # Per-sample analysis
    print("\nPer-sample analysis (first 1000 samples)...")
    per_sample = evaluate_per_sample(model, test_loader, device, 
                                      beta=args.beta, max_samples=1000)
    
    print(f"Reconstruction loss - Mean: {per_sample['reconstruction'].mean():.4f}, "
          f"Std: {per_sample['reconstruction'].std():.4f}")
    print(f"KL divergence - Mean: {per_sample['kl'].mean():.4f}, "
          f"Std: {per_sample['kl'].std():.4f}")
    print(f"Total loss - Mean: {per_sample['total'].mean():.4f}, "
          f"Std: {per_sample['total'].std():.4f}")
    
    # Save results
    results = {
        'average_losses': avg_losses,
        'per_sample_stats': {
            'recon_mean': float(per_sample['reconstruction'].mean()),
            'recon_std': float(per_sample['reconstruction'].std()),
            'kl_mean': float(per_sample['kl'].mean()),
            'kl_std': float(per_sample['kl'].std()),
            'total_mean': float(per_sample['total'].mean()),
            'total_std': float(per_sample['total'].std())
        },
        'model_config': config,
        'training_history': history
    }
    save_evaluation_results(results, args.results_path)
    
    # Generate visualizations
    print("\nGenerating evaluation visualizations...")
    generate_visualizations(model, test_loader, device, 
                            args.output_dir, args.num_samples)
    
    print("\nEvaluation completed successfully!")


if __name__ == "__main__":
    main()