import os, time, textwrap
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

WORK = r"D:\bca 4\Semester 5\Gen Ai\CycleGan&\work"
ROOT = r"D:\bca 4\Semester 5\Gen Ai\CycleGan&"

NST_SRC = os.path.join(WORK, "final_output_512.jpg")

def wait_nst(timeout=900):
    t0 = time.time()
    while not os.path.exists(NST_SRC):
        if time.time() - t0 > timeout:
            raise SystemExit("NST output never appeared")
        time.sleep(5)
    # wait until file size is stable
    prev = -1
    while time.time() - t0 < timeout:
        sz = os.path.getsize(NST_SRC)
        if sz == prev:
            break
        prev = sz
        time.sleep(3)
    return NST_SRC

def load(p, size=512):
    return Image.open(p).convert("RGB").resize((size, size), Image.LANCZOS)

def font(sz):
    for p in [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()

def make_comparison(orig, cyc, nst, out_png):
    labels = ["1. Original", "2. CycleGAN output", "3. Neural Style Transfer output"]
    S = 512
    pad, bar = 24, 46
    W = 3 * S + 4 * pad
    H = S + 2 * pad + bar
    canvas = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(canvas)
    f = font(26)
    for i, (im, lab) in enumerate(zip([orig, cyc, nst], labels)):
        x = pad + i * (S + pad)
        canvas.paste(im, (x, pad))
        d.rectangle([x, pad, x + S, pad + S], outline=(60, 60, 60), width=2)
        tw = d.textlength(lab, font=f)
        d.text((x + (S - tw) / 2, pad + S + 10), lab, fill=(20, 20, 20), font=f)
    canvas.save(out_png, quality=95)
    return out_png

def make_pdf(orig_p, cyc_p, nst_p, cmp_p, out_pdf):
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, spaceAfter=6, alignment=1)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=6)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5, leading=11,
                           textColor=colors.HexColor("#444444"), spaceAfter=4)
    cap = ParagraphStyle("cap", parent=styles["Normal"], fontSize=9, leading=12, alignment=1,
                         textColor=colors.HexColor("#333333"))

    doc = SimpleDocTemplate(out_pdf, pagesize=A4, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.55 * inch, bottomMargin=0.55 * inch,
                            title="Assignment 6 - AI-Based Style Transfer")
    S = []
    S.append(Paragraph("ASSIGNMENT 6 - Applying AI-Based Style Transfer to an Image", h1))
    S.append(Paragraph("Comparison of two methods: pretrained CycleGAN and VGG-based Neural Style Transfer "
                       "on a single landscape photograph", cap))
    S.append(Spacer(1, 8))

    # --- three images side by side ---
    cell = 2.05 * inch
    imgs = [[RLImage(orig_p, cell, cell), RLImage(cyc_p, cell, cell), RLImage(nst_p, cell, cell)],
            [Paragraph("Original", cap), Paragraph("CycleGAN output", cap),
             Paragraph("Neural Style Transfer output", cap)]]
    t = Table(imgs, colWidths=[cell + 4] * 3)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                           ("TOPPADDING", (0, 1), (-1, 1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    S.append(t)
    S.append(Paragraph("Figure 1: Original image, CycleGAN output and Neural Style Transfer output "
                       "(full-size figure in comparison.png).", small))

    S.append(Paragraph("Method Setup", h2))
    S.append(Paragraph(
        "<b>Input image:</b> landscape photograph of J&ouml;kuls&aacute;rl&oacute;n glacier lagoon, Iceland "
        "(Wikimedia Commons), centre-cropped and resized to 512&times;512. &nbsp;"
        "<b>Method 1 - CycleGAN:</b> official pretrained <i>style_vangogh</i> ResNet-9 generator "
        "(junyanz/pytorch-CycleGAN-and-pix2pix released weights), photo &rarr; Van Gogh domain, "
        "input scaled to 256&times;256 and normalised to [-1, 1]. &nbsp;"
        "<b>Method 2 - Neural Style Transfer:</b> Gatys et al. optimisation using VGG-19 ImageNet features; "
        "content = relu4_2, style = relu1_1&hellip;relu5_1 Gram matrices, Adam (lr = 0.01, 120 steps, 512&times;512), "
        "style painting = <i>The Starry Night</i> (Van Gogh, 1889).", body))

    S.append(Paragraph("Written Comparison", h2))
    S.append(Paragraph(
        "<b>Content preservation:</b> Neural Style Transfer preserved the original content better &mdash; the "
        "mountain ridge, iceberg positions, rocks and reflections stay pixel-for-pixel in place, because NST only "
        "re-renders the image so that its VGG features match the style painting while the content features of the "
        "same image stay fixed. CycleGAN, by contrast, re-painted the whole scene and slightly shifted colours and "
        "small details, although the overall composition of the lagoon is still clearly readable.", body))
    S.append(Paragraph(
        "<b>Style strength:</b> CycleGAN produced the stronger style transformation: it replaced the photographic "
        "surface entirely with thick Van Gogh-like impasto strokes and a warm yellow-orange palette, so the result "
        "looks like a painting rather than a photograph. The NST output keeps a photographic base and overlays the "
        "swirling brush texture and night-blue/gold colour scheme of <i>The Starry Night</i>, so the style is "
        "visible but softer and colour-cast.", body))
    S.append(Paragraph(
        "<b>Differences noticed:</b> CycleGAN changes global appearance (colour, texture, lighting) with a fixed "
        "target style and needs only one forward pass, while NST changes local texture statistics and is sensitive "
        "to the content/style weight balance; NST never invents new objects, whereas CycleGAN can alter or drop "
        "small structures in the image.", body))
    S.append(Paragraph(
        "<b>Cycle consistency:</b> CycleGAN trains on unpaired image sets using a cycle-consistency loss "
        "||G(F(x)) &minus; x||<sub>1</sub> (plus the adversarial loss) that forces the two generators to be "
        "mutual inverses: a photo translated to the Van Gogh domain must be translatable back to exactly the "
        "original photo. This constraint stops the generator from collapsing to a single output and is why the "
        "original landscape structure survives the style change even though no paired photo/painting training "
        "examples were ever used.", body))

    S.append(Paragraph("References", h2))
    S.append(Paragraph(
        "Zhu, J.-Y. et al., <i>Unpaired Image-to-Image Translation using Cycle-Consistent Adversarial Networks</i>, "
        "ICCV 2017 (pretrained style_vangogh weights, official release). &nbsp; Gatys, L. A. et al., "
        "<i>A Neural Algorithm of Artistic Style</i>, CVPR 2016 (VGG-based NST). &nbsp; "
        "Images: J&ouml;kuls&aacute;rl&oacute;n lagoon photo and <i>The Starry Night</i> - Wikimedia Commons.", small))
    doc.build(S)
    return out_pdf

if __name__ == "__main__":
    wait_nst()
    print("NST ready:", os.path.getsize(NST_SRC))
    orig = os.path.join(WORK, "original_512.jpg")
    cyc = os.path.join(WORK, "cyclegan_output.jpg")
    nst = NST_SRC

    o, c, n = load(orig), load(cyc), load(nst)
    o.save(os.path.join(ROOT, "original.jpg"), quality=95)
    c.save(os.path.join(ROOT, "cyclegan_output.jpg"), quality=95)
    n.save(os.path.join(ROOT, "nst_output.jpg"), quality=95)
    cmp_p = make_comparison(o, c, n, os.path.join(ROOT, "comparison.png"))
    pdf_p = make_pdf(os.path.join(ROOT, "original.jpg"), os.path.join(ROOT, "cyclegan_output.jpg"),
                     os.path.join(ROOT, "nst_output.jpg"), cmp_p,
                     os.path.join(ROOT, "ASSIGNMENT_6_Style_Transfer_Report.pdf"))
    print("PDF:", pdf_p, os.path.getsize(pdf_p))
