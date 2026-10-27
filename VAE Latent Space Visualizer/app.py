"""
VAE Latent Space Visualizer - Streamlit Application

Interactive visualization for exploring VAE latent space and reconstructions.
"""

import streamlit as st
import torch
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import json
import os
from pathlib import Path

# Add src to path
import sys
sys.path.append(str(Path(__file__).parent / 'src'))

from model import VAE, create_vae
from dataset import get_data_loaders
from losses import vae_loss, compute_losses_per_sample
from visualization import (plot_reconstruction_comparison, 
                            plot_latent_space,
                            plot_training_history,
                            plot_generated_grid,
                            plot_latent_traversal)


# Page configuration
st.set_page_config(
    page_title="VAE Latent Space Visualizer",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)


# Custom CSS for academic styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 600;
        color: #1f2937;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #6b7280;
        margin-bottom: 2rem;
    }
    .section-header {
        font-size: 1.5rem;
        font-weight: 600;
        color: #374151;
        margin-top: 2rem;
        margin-bottom: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #e5e7eb;
    }
    .metric-card {
        background: #f9fafb;
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid #e5e7eb;
    }
    .stAlert > div {
        padding: 1rem;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_device():
    """Get the best available device."""
    if torch.cuda.is_available():
        return torch.device('cuda')
    return torch.device('cpu')


@st.cache_resource
def load_model_and_data(checkpoint_path: str):
    """Load model checkpoint and test data loader."""
    device = get_device()
    
    if not os.path.exists(checkpoint_path):
        return None, None, None, None, f"Checkpoint not found: {checkpoint_path}"
    
    try:
        checkpoint = torch.load(checkpoint_path, map_location=device)
        config = checkpoint.get('config', {})
        
        model = create_vae(config).to(device)
        model.load_state_dict(checkpoint['model_state_dict'])
        model.eval()
        
        _, test_loader = get_data_loaders(batch_size=128)
        
        history = checkpoint.get('history', {})
        architecture = model.get_architecture_summary()
        
        return model, test_loader, history, architecture, None
    except Exception as e:
        return None, None, None, None, f"Error loading model: {str(e)}"


@st.cache_data
def get_test_batch(test_loader, device, num_samples=10):
    """Get a batch of test images for reconstruction."""
    model = None  # Will be passed in
    images, labels = next(iter(test_loader))
    images = images.to(device)
    return images[:num_samples], labels[:num_samples]


def encode_batch(model, images):
    """Encode a batch of images to latent space."""
    with torch.no_grad():
        mu, logvar = model.encode(images)
        z = model.reparameterize(mu, logvar)
        recon = model.decode(z)
    return mu, logvar, z, recon


def main():
    # Header
    st.markdown('<h1 class="main-header">VAE Latent Space Visualizer</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Exploring dimensionality reduction, probabilistic latent representations, and image reconstruction using a Variational Autoencoder.</p>', unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.header("Configuration")
        
        checkpoint_path = st.text_input(
            "Model Checkpoint Path",
            value="models/vae_mnist.pth",
            help="Path to the trained VAE checkpoint"
        )
        
        beta = st.slider(
            "β (KL Weight)",
            min_value=0.0,
            max_value=5.0,
            value=1.0,
            step=0.1,
            help="Weight for KL divergence term in loss"
        )
        
        st.divider()
        
        # Device info
        device = get_device()
        st.info(f"**Device:** {device.type.upper()}")
        if device.type == 'cuda':
            st.info(f"**GPU:** {torch.cuda.get_device_name(0)}")
        
        st.divider()
        
        # Training command hint
        if not os.path.exists(checkpoint_path):
            st.warning("⚠️ No trained model found!")
            st.code("python train.py", language="bash")
            st.caption("Run this command to train the VAE first.")
    
    # Load model
    model, test_loader, history, architecture, error = load_model_and_data(checkpoint_path)
    
    if error:
        st.error(error)
        st.stop()
    
    # Get test batch for reconstructions
    test_images, test_labels = next(iter(test_loader))
    test_images = test_images.to(device)
    test_labels = test_labels.to(device)
    
    # ============================================================
    # SECTION 1: Original vs Reconstructed Images
    # ============================================================
    st.markdown('<h2 class="section-header">1. Original vs Reconstructed Images</h2>', unsafe_allow_html=True)
    
    col1, col2 = st.columns([1, 3])
    
    with col1:
        # Sample selector
        sample_idx = st.selectbox(
            "Select Sample",
            options=list(range(min(10, len(test_images)))),
            format_func=lambda x: f"Sample {x} (Digit: {test_labels[x].item()})"
        )
        
        # Show reconstruction loss for selected sample
        with torch.no_grad():
            recon, mu, logvar = model(test_images[sample_idx:sample_idx+1])
            losses = vae_loss(recon, test_images[sample_idx:sample_idx+1], mu, logvar, beta=beta)
            recon_loss = losses['reconstruction'].item()
            kl_loss = losses['kl'].item()
            total_loss = losses['total'].item()
        
        st.metric("Reconstruction Loss (BCE)", f"{recon_loss:.4f}")
        st.metric("KL Divergence", f"{kl_loss:.4f}")
        st.metric("Total Loss", f"{total_loss:.4f}")
        
        # Latent coordinates
        st.write("**Latent Coordinates (μ):**")
        st.write(f"z₁ = {mu[0, 0].item():.4f}")
        st.write(f"z₂ = {mu[0, 1].item():.4f}")
    
    with col2:
        # Plot reconstruction comparison
        with torch.no_grad():
            recon_batch, _, _ = model(test_images[:10])
        
        fig = plot_reconstruction_comparison(
            test_images[:10].cpu(), recon_batch.cpu(), test_labels[:10].cpu(),
            num_samples=10
        )
        st.pyplot(fig)
        plt.close(fig)
    
    # ============================================================
    # SECTION 2: Interactive Latent Space
    # ============================================================
    st.markdown('<h2 class="section-header">2. Interactive Latent Space</h2>', unsafe_allow_html=True)
    
    tab1, tab2 = st.tabs(["Latent Space Scatter", "Latent Space Generation"])
    
    with tab1:
        st.write("2D scatter plot of encoded MNIST test images. Points colored by digit label.")
        
        # Option to limit samples for performance
        num_scatter_samples = st.slider(
            "Number of samples for scatter plot",
            min_value=500,
            max_value=5000,
            value=2000,
            step=500
        )
        
        with st.spinner("Encoding test set..."):
            fig = plot_latent_space(model, test_loader, device, num_samples=num_scatter_samples)
            st.pyplot(fig)
            plt.close(fig)
    
    with tab2:
        st.write("Adjust latent coordinates (z₁, z₂) to generate new digit images.")
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            # Latent sliders
            z1 = st.slider("Latent Dimension 1 (z₁)", -3.0, 3.0, 0.0, 0.1)
            z2 = st.slider("Latent Dimension 2 (z₂)", -3.0, 3.0, 0.0, 0.1)
            
            # Generate from latent coordinates
            with torch.no_grad():
                z = torch.tensor([[z1, z2]], dtype=torch.float32).to(device)
                generated = model.decode(z).cpu().squeeze().numpy()
            
            # Display generated image
            fig, ax = plt.subplots(figsize=(3, 3))
            ax.imshow(generated, cmap='gray', vmin=0, vmax=1)
            ax.axis('off')
            ax.set_title(f'Generated (z₁={z1:.1f}, z₂={z2:.1f})')
            st.pyplot(fig)
            plt.close(fig)
        
        with col2:
            # Show full grid
            st.write("**Full Latent Space Grid (15×15):**")
            with st.spinner("Generating grid..."):
                fig = plot_generated_grid(model.decoder, device, grid_size=15)
                st.pyplot(fig)
                plt.close(fig)
    
    # ============================================================
    # SECTION 3: Training Loss Visualization
    # ============================================================
    st.markdown('<h2 class="section-header">3. Training Loss Visualization</h2>', unsafe_allow_html=True)
    
    if history and 'recon_loss' in history and len(history['recon_loss']) > 0:
        fig = plot_training_history(history)
        st.pyplot(fig)
        plt.close(fig)
        
        # Show final values
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Final Recon Loss", f"{history['recon_loss'][-1]:.4f}")
        with col2:
            st.metric("Final KL Loss", f"{history['kl_loss'][-1]:.4f}")
        with col3:
            st.metric("Final Total Loss", f"{history['total_loss'][-1]:.4f}")
    else:
        st.info("No training history available. Train the model to see loss curves.")
    
    # ============================================================
    # SECTION 4: Model Evaluation
    # ============================================================
    st.markdown('<h2 class="section-header">4. Model Evaluation</h2>', unsafe_allow_html=True)
    
    # Evaluate on full test set
    with st.spinner("Evaluating on test set..."):
        eval_losses = evaluate_on_test_set(model, test_loader, device, beta)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Test Reconstruction Loss", f"{eval_losses['reconstruction_loss']:.6f}")
    with col2:
        st.metric("Test KL Divergence", f"{eval_losses['kl_divergence']:.6f}")
    with col3:
        st.metric("Test Total Loss", f"{eval_losses['total_loss']:.6f}")
    
    # Architecture summary
    st.subheader("Model Architecture")
    
    arch_col1, arch_col2 = st.columns(2)
    
    with arch_col1:
        st.write("**Configuration:**")
        st.json({
            "Input Dimension": architecture['input_dim'],
            "Latent Dimension": architecture['latent_dim'],
            "Hidden Dimensions": architecture['hidden_dims'],
            "Total Parameters": f"{architecture['num_parameters']:,}"
        })
    
    with arch_col2:
        st.write("**Encoder Layers:**")
        for layer in architecture['encoder_layers']:
            st.code(layer)
        
        st.write("**Decoder Layers:**")
        for layer in architecture['decoder_layers']:
            st.code(layer)


def evaluate_on_test_set(model, test_loader, device, beta):
    """Evaluate model on full test set."""
    model.eval()
    total_recon = 0.0
    total_kl = 0.0
    total_loss = 0.0
    num_batches = 0
    
    with torch.no_grad():
        for images, _ in test_loader:
            images = images.to(device)
            recon, mu, logvar = model(images)
            losses = vae_loss(recon, images, mu, logvar, beta=beta)
            total_recon += losses['reconstruction'].item()
            total_kl += losses['kl'].item()
            total_loss += losses['total'].item()
            num_batches += 1
    
    return {
        'reconstruction_loss': total_recon / num_batches,
        'kl_divergence': total_kl / num_batches,
        'total_loss': total_loss / num_batches
    }


if __name__ == "__main__":
    main()