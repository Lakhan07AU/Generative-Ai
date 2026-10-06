import os, time, math, sys
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models
from PIL import Image

WORK = r"D:\bca 4\Semester 5\Gen Ai\CycleGan&\work"

SIZE = int(os.environ.get("NST_SIZE", 512))
STEPS = int(os.environ.get("NST_STEPS", 300))
LR = float(os.environ.get("NST_LR", 0.01))
STYLE_W = float(os.environ.get("NST_STYLE_W", 1.0))
CONTENT_W = float(os.environ.get("NST_CONTENT_W", 1.0))
TV_W = float(os.environ.get("NST_TV_W", 0.0))
TAG = os.environ.get("NST_TAG", "nst")

MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)

STYLE_IDX = [1, 6, 11, 20, 29]     # relu1_1 .. relu5_1
CONTENT_IDX = [22]                  # relu4_2
ALL_IDX = sorted(set(STYLE_IDX + CONTENT_IDX))


def load_img(path, size, resize_short=True):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
    im = im.resize((size, size), Image.LANCZOS)
    t = torch.from_numpy(np.array(im, dtype=np.float32)).permute(2, 0, 1) / 255.0
    return t.unsqueeze(0)


def denorm(x):
    x = x.detach().squeeze(0).cpu().clamp(0, 1)
    return Image.fromarray((x.permute(1, 2, 0).numpy() * 255).round().astype("uint8"))


def gram(f):
    b, c, h, w = f.shape
    f = f.view(b, c, h * w)
    return torch.bmm(f, f.transpose(1, 2)) / (c * h * w)


def main():
    device = torch.device("cpu")
    print("size", SIZE, "steps", STEPS, "lr", LR, "style_w", STYLE_W, "content_w", CONTENT_W)

    content = load_img(os.path.join(WORK, "original_square_512.jpg"), SIZE).to(device)
    style = load_img(os.path.join(WORK, "style_starry_night.jpg"), SIZE).to(device)

    t0 = time.time()
    vgg = models.vgg19(weights=models.VGG19_Weights.IMAGENET1K_V1).features.eval().to(device)
    for p in vgg.parameters():
        p.requires_grad_(False)
    print("vgg loaded %.1fs" % (time.time() - t0))

    def feats(x, idxs):
        h = x
        out = {}
        for i, layer in enumerate(vgg):
            h = layer(h)
            if i in idxs:
                out[i] = h
            if i >= max(idxs):
                break
        return out

    with torch.no_grad():
        c_feats = feats((content - MEAN) / STD, set(CONTENT_IDX))
        s_feats = feats((style - MEAN) / STD, set(STYLE_IDX))

    for k, v in c_feats.items():
        print("content feat", k, tuple(v.shape))
    for k, v in s_feats.items():
        print("style feat", k, tuple(v.shape))

    # start from a mildly noisy content image? start from content
    init = os.environ.get("NST_INIT")
    img = (load_img(init, SIZE) if init else content.clone()).requires_grad_(True)
    opt = torch.optim.Adam([img], lr=LR)

    out_dir = os.path.join(WORK, "nst_progress_%s" % TAG)
    os.makedirs(out_dir, exist_ok=True)

    for step in range(1, STEPS + 1):
        opt.zero_grad()
        norm = (img - MEAN) / STD
        f = feats(norm, set(ALL_IDX))

        style_loss = img.new_zeros(())
        for i in STYLE_IDX:
            style_loss = style_loss + F.mse_loss(gram(f[i]), gram(s_feats[i]))
        style_loss = style_loss / len(STYLE_IDX)

        content_loss = img.new_zeros(())
        for i in CONTENT_IDX:
            content_loss = content_loss + F.mse_loss(f[i], c_feats[i])

        loss = STYLE_W * style_loss + CONTENT_W * content_loss
        if TV_W > 0:
            tv = (img[:, :, :, :-1] - img[:, :, :, 1:]).abs().mean() + (img[:, :, :-1, :] - img[:, :, 1:, :]).abs().mean()
            loss = loss + TV_W * tv
        loss.backward()
        opt.step()
        img.data.clamp_(0, 1)

        if step % 25 == 0 or step == 1:
            print("step %4d  total %.4f  style %.5f  content %.5f  (%.1fs)" %
                  (step, loss.item(), style_loss.item(), content_loss.item(), time.time() - t0), flush=True)
            denorm(img).save(os.path.join(out_dir, "step_%04d.jpg" % step), quality=92)

    final = denorm(img)
    final.save(os.path.join(WORK, "%s_output_%d.jpg" % (TAG, SIZE)), quality=95)
    print("saved final", time.time() - t0, "sec")


if __name__ == "__main__":
    main()
