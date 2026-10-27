"""
VAE Training Pipeline for MNIST

Trains a Variational Autoencoder on MNIST dataset with:
- Automatic CPU/CUDA detection
- Adam optimizer
- Configurable epochs, batch size, learning rate
- Training history tracking
- Model checkpointing
- Visualization generation
"""

import os
import json
import argparse
import torch
import torch.optim as optim
from tqdm import tqdm
import numpy as np

from src.model import VAE, create_vae
from src.dataset import get_data_loaders
from src.losses import vae_loss
from src.visualization import save_all_visualizations


def set_seed(seed: int = 42):
    """Set random seeds for reproducibility."""
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def get_device() -> torch.device:
    """Get the best available device (CUDA or CPU)."""
    if torch.cuda.is_available():
        device = torch.device('cuda')
        print(f"Using GPU: {torch.cuda.get_device_name(0)}")
    else:
        device = torch.device('cpu')
        print("Using CPU")
    return device


def get_beta(epoch: int, max_epochs: int, beta_max: float = 1.0,
             warmup_epochs: int = 5) -> float:
    """
    KL annealing: linearly increase beta from 0 to beta_max over warmup_epochs.
    
    This prevents posterior collapse by allowing the model to first learn
    to use the latent code before applying KL regularization.
    """
    if warmup_epochs <= 0:
        return beta_max
    beta = beta_max * min(1.0, epoch / warmup_epochs)
    return beta


def train_epoch(model: VAE, train_loader, optimizer, device: torch.device,
                beta: float = 1.0, free_bits: float = 0.5) -> dict:
    """
    Train for one epoch.
    
    Returns:
        Dictionary with average losses for the epoch
    """
    model.train()
    
    total_recon = 0.0
    total_kl = 0.0
    total_loss = 0.0
    num_batches = 0
    
    for images, _ in tqdm(train_loader, desc="Training", leave=False):
        images = images.to(device)
        
        optimizer.zero_grad()
        
        recon, mu, logvar = model(images)
        losses = vae_loss(recon, images, mu, logvar, beta=beta, free_bits=free_bits)
        
        losses['total'].backward()
        optimizer.step()
        
        total_recon += losses['reconstruction'].item()
        total_kl += losses['kl'].item()
        total_loss += losses['total'].item()
        num_batches += 1
    
    return {
        'recon_loss': total_recon / num_batches,
        'kl_loss': total_kl / num_batches,
        'total_loss': total_loss / num_batches
    }


def evaluate(model: VAE, test_loader, device: torch.device,
             beta: float = 1.0, free_bits: float = 0.5) -> dict:
    """
    Evaluate model on test set.
    
    Returns:
        Dictionary with average test losses
    """
    model.eval()
    
    total_recon = 0.0
    total_kl = 0.0
    total_loss = 0.0
    num_batches = 0
    
    with torch.no_grad():
        for images, _ in tqdm(test_loader, desc="Evaluating", leave=False):
            images = images.to(device)
            
            recon, mu, logvar = model(images)
            losses = vae_loss(recon, images, mu, logvar, beta=beta, free_bits=free_bits)
            
            total_recon += losses['reconstruction'].item()
            total_kl += losses['kl'].item()
            total_loss += losses['total'].item()
            num_batches += 1
    
    return {
        'recon_loss': total_recon / num_batches,
        'kl_loss': total_kl / num_batches,
        'total_loss': total_loss / num_batches
    }


def save_checkpoint(model: VAE, optimizer, epoch: int, history: dict,
                    config: dict, path: str):
    """Save model checkpoint with configuration and history."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    checkpoint = {
        'epoch': epoch,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'history': history,
        'config': config,
        'architecture': model.get_architecture_summary()
    }
    
    torch.save(checkpoint, path)
    print(f"Checkpoint saved to {path}")


def load_checkpoint(path: str, device: torch.device) -> dict:
    """Load model checkpoint."""
    checkpoint = torch.load(path, map_location=device)
    return checkpoint


def train(config: dict = None):
    """
    Main training function.
    
    Args:
        config: Training configuration dictionary
    """
    # Default configuration
    default_config = {
        'input_dim': 784,
        'hidden_dims': [512, 256],
        'latent_dim': 2,
        'batch_size': 128,
        'learning_rate': 0.001,
        'epochs': 15,
        'beta': 1.0,
        'warmup_epochs': 5,
        'free_bits': 0.5,
        'seed': 42,
        'data_root': './data',
        'checkpoint_path': 'models/vae_mnist.pth',
        'history_path': 'outputs/training_history.json'
    }
    
    if config:
        default_config.update(config)
    config = default_config
    
    # Set seed
    set_seed(config['seed'])
    
    # Get device
    device = get_device()
    
    # Create model
    model = create_vae(config).to(device)
    print(f"Model created: {model.get_num_parameters():,} parameters")
    
    # Create optimizer
    optimizer = optim.Adam(model.parameters(), lr=config['learning_rate'])
    
    # Get data loaders
    train_loader, test_loader = get_data_loaders(
        batch_size=config['batch_size'],
        data_root=config['data_root']
    )
    
    # Training history
    history = {
        'recon_loss': [],
        'kl_loss': [],
        'total_loss': [],
        'test_recon_loss': [],
        'test_kl_loss': [],
        'test_total_loss': []
    }
    
    print(f"\nStarting training for {config['epochs']} epochs...")
    print(f"Batch size: {config['batch_size']}, Learning rate: {config['learning_rate']}")
    print(f"Beta (KL weight): {config['beta']}")
    print(f"Device: {device}")
    print("-" * 50)
    
    warmup_epochs = config.get('warmup_epochs', 5)
    free_bits = config.get('free_bits', 0.5)
    
    for epoch in range(1, config['epochs'] + 1):
        # KL annealing: gradually increase beta from 0 to target
        current_beta = get_beta(epoch, config['epochs'], 
                                beta_max=config['beta'],
                                warmup_epochs=warmup_epochs)
        
        # Train
        train_losses = train_epoch(model, train_loader, optimizer, device, 
                                   beta=current_beta, free_bits=free_bits)
        
        # Evaluate with full beta
        test_losses = evaluate(model, test_loader, device, beta=current_beta,
                              free_bits=free_bits)
        
        # Record history
        history['recon_loss'].append(train_losses['recon_loss'])
        history['kl_loss'].append(train_losses['kl_loss'])
        history['total_loss'].append(train_losses['total_loss'])
        history['test_recon_loss'].append(test_losses['recon_loss'])
        history['test_kl_loss'].append(test_losses['kl_loss'])
        history['test_total_loss'].append(test_losses['total_loss'])
        
        # Print progress
        print(f"Epoch {epoch:3d}/{config['epochs']} | beta={current_beta:.2f} | "
              f"Train: Recon={train_losses['recon_loss']:.4f} "
              f"KL={train_losses['kl_loss']:.4f} "
              f"Total={train_losses['total_loss']:.4f} | "
              f"Test: Recon={test_losses['recon_loss']:.4f} "
              f"KL={test_losses['kl_loss']:.4f} "
              f"Total={test_losses['total_loss']:.4f}")
    
    # Save checkpoint
    save_checkpoint(model, optimizer, config['epochs'], history, config,
                    config['checkpoint_path'])
    
    # Save history
    os.makedirs(os.path.dirname(config['history_path']), exist_ok=True)
    with open(config['history_path'], 'w') as f:
        json.dump(history, f, indent=2)
    print(f"Training history saved to {config['history_path']}")
    
    # Generate visualizations
    print("\nGenerating visualizations...")
    save_all_visualizations(model, train_loader, test_loader, device, history)
    
    print("\nTraining completed successfully!")
    return model, history


def main():
    parser = argparse.ArgumentParser(description='Train VAE on MNIST')
    parser.add_argument('--epochs', type=int, default=15, help='Number of epochs')
    parser.add_argument('--batch-size', type=int, default=128, help='Batch size')
    parser.add_argument('--lr', type=float, default=0.001, help='Learning rate')
    parser.add_argument('--beta', type=float, default=1.0, help='KL weight')
    parser.add_argument('--warmup-epochs', type=int, default=5, help='KL annealing warmup epochs')
    parser.add_argument('--free-bits', type=float, default=0.5, help='Free bits per latent dimension')
    parser.add_argument('--latent-dim', type=int, default=2, help='Latent dimension')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    parser.add_argument('--checkpoint', type=str, default='models/vae_mnist.pth',
                        help='Checkpoint path')
    
    args = parser.parse_args()
    
    config = {
        'epochs': args.epochs,
        'batch_size': args.batch_size,
        'learning_rate': args.lr,
        'beta': args.beta,
        'warmup_epochs': args.warmup_epochs,
        'free_bits': args.free_bits,
        'latent_dim': args.latent_dim,
        'seed': args.seed,
        'checkpoint_path': args.checkpoint
    }
    
    train(config)


if __name__ == "__main__":
    main()