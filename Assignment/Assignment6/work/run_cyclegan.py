import functools, os, sys
import torch
import torch.nn as nn
from PIL import Image

WORK = r"D:\bca 4\Semester 5\Gen Ai\CycleGan&\work"
OUT = WORK
CKPT = os.path.join(WORK, "style_vangogh.pth")

sys.path.insert(0, WORK)
import networks_reference as networks

def build_generator():
    norm_layer = functools.partial(nn.InstanceNorm2d, affine=False, track_running_stats=True)
    net = networks.ResnetGenerator(3, 3, ngf=64, norm_layer=norm_layer, use_dropout=False,
                                   n_blocks=9, padding_type="reflect")
    sd = torch.load(CKPT, map_location="cpu")
    missing, unexpected = net.load_state_dict(sd, strict=False)
    print("missing:", missing)
    print("unexpected:", unexpected)
    net.eval()  # placeholder; we run in train-mode for instance norm stats
    return net

def load_square(path, size):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
    return im.resize((size, size), Image.LANCZOS)

def to_tensor(im):
    x = torch.from_numpy(__import__("numpy").asarray(im)).float() / 255.0
    x = x.permute(2, 0, 1).unsqueeze(0)
    return x * 2.0 - 1.0

def to_pil(x):
    import numpy as np
    x = (x.squeeze(0).detach().clamp(-1, 1) + 1.0) * 0.5
    arr = (x.permute(1, 2, 0).numpy() * 255.0).round().astype("uint8")
    return Image.fromarray(arr)

def main():
    net = build_generator()
    net.train()  # InstanceNorm uses per-image statistics (same as official test.py default)

    photo = load_square(os.path.join(WORK, "input_raw.jpg"), 256)
    style = load_square(os.path.join(WORK, "style_starry_night.jpg"), 256)

    with torch.no_grad():
        out_photo = net(to_tensor(photo))
        out_style = net(to_tensor(style))

    to_pil(out_photo).save(os.path.join(OUT, "cyc_photo_as_input.jpg"), quality=95)
    to_pil(out_style).save(os.path.join(OUT, "cyc_style_as_input.jpg"), quality=95)
    photo.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, "original_square_512.jpg"), quality=95)
    print("saved; check which direction translates photo -> painting")

if __name__ == "__main__":
    main()
