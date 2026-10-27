import sys
sys.path.append('src')
import torch
from model import VAE
from dataset import get_data_loaders
from losses import vae_loss

device = torch.device('cpu')
model = VAE().to(device)
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

_, test_loader = get_data_loaders(batch_size=128)
images, _ = next(iter(test_loader))
images = images.to(device)

# Train for 5 steps with beta=0 (no KL) to see if encoder learns
print('=== Training with beta=0 (no KL penalty) ===')
model.train()
for step in range(5):
    optimizer.zero_grad()
    recon, mu, logvar = model(images)
    losses = vae_loss(recon, images, mu, logvar, beta=0.0)
    losses['total'].backward()
    optimizer.step()
    print('Step %d: recon=%.4f, mu=%.4f/%.4f, logvar=%.4f/%.4f' % (
        step+1, losses['reconstruction'].item(),
        mu.mean(0)[0].item(), mu.mean(0)[1].item(),
        logvar.mean(0)[0].item(), logvar.mean(0)[1].item()))

# Now check if decoder uses latent code
model.eval()
with torch.no_grad():
    z1 = torch.tensor([[0.0, 0.0]], dtype=torch.float32).to(device)
    z2 = torch.tensor([[3.0, 3.0]], dtype=torch.float32).to(device)
    r1 = model.decode(z1)
    r2 = model.decode(z2)
print('\nLatent code usage after beta=0 training:')
print('  recon at z=[0,0] mean: %.4f' % r1.mean().item())
print('  recon at z=[3,3] mean: %.4f' % r2.mean().item())
print('  difference: %.4f' % (r1-r2).abs().mean().item())