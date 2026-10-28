"""
MNIST Dataset Handling for VAE

Provides data loaders for training and testing with proper normalization.
"""

import torch
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, transforms
import numpy as np


def get_mnist_transforms() -> transforms.Compose:
    """
    Get standard MNIST transforms: ToTensor and Normalize to [0, 1].
    
    Returns:
        Compose transform pipeline
    """
    return transforms.Compose([
        transforms.ToTensor(),  # Converts to [0, 1] range
    ])


def get_data_loaders(batch_size: int = 128, 
                     num_workers: int = 0,
                     pin_memory: bool = True,
                     data_root: str = './data') -> tuple:
    """
    Create train and test data loaders for MNIST.
    
    Args:
        batch_size: Batch size for data loaders
        num_workers: Number of worker processes for data loading
        pin_memory: Whether to pin memory for faster GPU transfer
        data_root: Root directory for dataset storage
        
    Returns:
        train_loader: DataLoader for training set (60,000 images)
        test_loader: DataLoader for test set (10,000 images)
    """
    transform = get_mnist_transforms()
    
    train_dataset = datasets.MNIST(
        root=data_root,
        train=True,
        download=True,
        transform=transform
    )
    
    test_dataset = datasets.MNIST(
        root=data_root,
        train=False,
        download=True,
        transform=transform
    )
    
    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        pin_memory=pin_memory
    )
    
    test_loader = DataLoader(
        test_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=pin_memory
    )
    
    return train_loader, test_loader


def get_subset_loader(dataset, indices: list, batch_size: int = 128,
                      shuffle: bool = False, num_workers: int = 0) -> DataLoader:
    """
    Create a DataLoader for a subset of the dataset.
    
    Args:
        dataset: The full dataset
        indices: List of indices to include
        batch_size: Batch size
        shuffle: Whether to shuffle
        num_workers: Number of workers
        
    Returns:
        DataLoader for the subset
    """
    subset = Subset(dataset, indices)
    return DataLoader(
        subset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers
    )


def display_sample_images(dataset, num_samples: int = 10) -> None:
    """
    Display sample images from the dataset (for verification).
    
    Args:
        dataset: MNIST dataset
        num_samples: Number of samples to display
    """
    import matplotlib.pyplot as plt
    
    fig, axes = plt.subplots(1, num_samples, figsize=(15, 3))
    for i in range(num_samples):
        img, label = dataset[i]
        axes[i].imshow(img.squeeze(), cmap='gray')
        axes[i].set_title(f'Label: {label}')
        axes[i].axis('off')
    plt.tight_layout()
    plt.show()


def get_test_subset_indices(test_dataset, num_samples: int = 1000) -> list:
    """
    Get indices for a balanced subset of test data (100 per class).
    
    Args:
        test_dataset: MNIST test dataset
        num_samples: Total number of samples (should be multiple of 10)
        
    Returns:
        List of indices
    """
    targets = test_dataset.targets.numpy()
    indices = []
    samples_per_class = num_samples // 10
    
    for digit in range(10):
        digit_indices = np.where(targets == digit)[0]
        selected = np.random.choice(digit_indices, samples_per_class, replace=False)
        indices.extend(selected.tolist())
    
    return indices


if __name__ == "__main__":
    # Test dataset loading
    train_loader, test_loader = get_data_loaders(batch_size=128)
    print(f"Train batches: {len(train_loader)}")
    print(f"Test batches: {len(test_loader)}")
    
    # Check shapes
    for images, labels in train_loader:
        print(f"Batch image shape: {images.shape}")
        print(f"Batch label shape: {labels.shape}")
        print(f"Image range: [{images.min():.4f}, {images.max():.4f}]")
        break
    
    print("Dataset loading successful!")