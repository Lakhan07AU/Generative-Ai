import functools, os, sys, torch, torch.nn as nn
from PIL import Image
import numpy as np

WORK = r"D:\bca 4\Semester 5\Gen Ai\CycleGan&\work"
sys.path.insert(0, WORK)
import networks_reference as networks

net = networks.ResnetGenerator(3, 3, ngf=64,
                               norm_layer=functools.partial(nn.InstanceNorm2d, affine=False, track_running_stats=True),
                               use_dropout=False, n_blocks=9, padding_type="reflect")
net.load_state_dict(torch.load(os.path.join(WORK, "style_vangogh.pth"), map_location="cpu"))
net.train()

def load_square(path, size):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
    return im.resize((size, size), Image.LANCZOS)

def run(im):
    x = torch.from_numpy(np.array(im, dtype=np.float32)).permute(2, 0, 1)[None] / 127.5 - 1.0
    with torch.no_grad():
        y = net(x)
    a = ((y[0].clamp(-1, 1) + 1) * 127.5).round().byte().permute(1, 2, 0).numpy()
    return Image.fromarray(a)

photo = load_square(os.path.join(WORK, "input_raw.jpg"), 512)
photo.save(os.path.join(WORK, "original_512.jpg"), quality=95)

out512 = run(photo)
out512.save(os.path.join(WORK, "cyclegan_output.jpg"), quality=95)

photo256 = photo.resize((256, 256), Image.LANCZOS)
out256 = run(photo256).resize((512, 512), Image.LANCZOS)
out256.save(os.path.join(WORK, "cyclegan_output_256.jpg"), quality=95)
print("saved cyclegan_output.jpg (512 input) and cyclegan_output_256.jpg (256 input)")
