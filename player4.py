import os
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser
from PIL import Image, ImageTk, ImageOps, ImageEnhance, ImageChops
import numpy as np

SUPPORTED_FORMATS = [
    ("Image files", ".png .jpg .jpeg .bmp .gif .tif .tiff .webp"),
    ("All files", "*.*"),
]

PREVIEW_MAX_SIZE = 512  # Max preview dimension for performance

def invert_image_keep_alpha(img: Image.Image) -> Image.Image:
    if img.mode == "RGBA":
        r,g,b,a = img.split()
        rgb = Image.merge("RGB",(r,g,b))
        inv = ImageOps.invert(rgb)
        r2,g2,b2 = inv.split()
        return Image.merge("RGBA",(r2,g2,b2,a))
    else:
        return ImageOps.invert(img.convert("RGB"))

def blend_images(base_img, top_img, mode='normal'):
    base = base_img.convert('RGB')
    top = top_img.convert('RGB').resize(base.size, Image.LANCZOS)
    if mode=='normal':
        return Image.blend(base, top, 0.5)
    elif mode=='multiply':
        return ImageChops.multiply(base, top)
    elif mode=='screen':
        return ImageChops.screen(base, top)
    elif mode=='overlay':
        b = np.asarray(base).astype(np.float32)/255.0
        t = np.asarray(top).astype(np.float32)/255.0
        out = np.zeros_like(b)
        mask = b<=0.5
        out[mask] = 2*b[mask]*t[mask]
        out[~mask] = 1-2*(1-b[~mask])*(1-t[~mask])
        return Image.fromarray(np.clip(out*255,0,255).astype(np.uint8))
    return base

class ImageEditorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Image Editor Advanced")
        self.root.geometry("1000x700")

        self.original_image: Image.Image | None = None
        self.processed_fullres: Image.Image | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None

        self.brightness_factor = 1.0
        self.invert = False
        self.highlight_color = (255,255,255)
        self.gradient_map_image: Image.Image | None = None
        self.gradient_blend_mode = 'normal'
        self.texture_image: Image.Image | None = None

        self.preview_after_id = None

        self._build_ui()
        self._bind_shortcuts()

    def _build_ui(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self.open_image)
        file_menu.add_command(label="Save As…", accelerator="Ctrl+S", command=self.save_image_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        blend_menu = tk.Menu(menubar, tearoff=0)
        for mode in ['normal','multiply','screen','overlay']:
            blend_menu.add_radiobutton(label=mode.capitalize(), command=lambda m=mode: self.set_blend_mode(m))
        menubar.add_cascade(label="Gradient Blend Mode", menu=blend_menu)

        self.root.config(menu=menubar)

        toolbar = ttk.Frame(self.root, padding=(10,8))
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar,text="Open",command=self.open_image).pack(side=tk.LEFT)
        ttk.Button(toolbar,text="Save",command=self.save_image_as).pack(side=tk.LEFT,padx=(6,0))

        ttk.Label(toolbar,text="Luminance").pack(side=tk.LEFT,padx=(12,0))
        self.brightness_var = tk.DoubleVar(value=100.0)
        self.brightness_slider = ttk.Scale(toolbar,from_=0,to=200,variable=self.brightness_var,
                                           command=lambda e:self._schedule_preview_update())
        self.brightness_slider.pack(side=tk.LEFT,fill=tk.X,expand=True,padx=(6,6))
        self.brightness_value_lbl = ttk.Label(toolbar,text="100%")
        self.brightness_value_lbl.pack(side=tk.LEFT)

        self.invert_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(toolbar,text="Invert",variable=self.invert_var,
                        command=lambda:self._schedule_preview_update()).pack(side=tk.LEFT,padx=(12,0))

        ttk.Button(toolbar,text="Highlight Color",command=self.choose_highlight_color).pack(side=tk.LEFT,padx=(12,0))
        ttk.Button(toolbar,text="Load Gradient Map",command=self.load_gradient_map).pack(side=tk.LEFT,padx=(12,0))
        ttk.Button(toolbar,text="Load Texture",command=self.load_texture).pack(side=tk.LEFT,padx=(12,0))
        ttk.Button(toolbar,text="Reset",command=self.reset_adjustments).pack(side=tk.LEFT,padx=(8,0))

        self.canvas = tk.Canvas(self.root,background="#1e1e1e",highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH,expand=True)
        self.canvas.bind("<Configure>", lambda e:self._schedule_preview_update())

    def _bind_shortcuts(self):
        self.root.bind("<Control-o>", lambda e:self.open_image())
        self.root.bind("<Control-s>", lambda e:self.save_image_as())
        self.root.bind("<Control-i>", lambda e:self.toggle_invert())
        self.root.bind("r", lambda e:self.reset_adjustments())

    def open_image(self):
        path = filedialog.askopenfilename(filetypes=SUPPORTED_FORMATS)
        if path:
            img = Image.open(path)
            self.original_image = img.convert("RGBA") if img.mode in ("P","1") else img.copy()
            self.reset_adjustments()
            self.root.title(f"Image Editor – {os.path.basename(path)}")

    def save_image_as(self):
        if self.original_image is None: return
        self._apply_fullres()
        path = filedialog.asksaveasfilename(defaultextension=".png",
                                            filetypes=[("PNG","*.png"),("JPEG","*.jpg *.jpeg"),("All files","*.*")])
        if path:
            img_to_save = self.processed_fullres
            if path.lower().endswith(('.jpg','.jpeg')):
                img_to_save = img_to_save.convert('RGB')
            img_to_save.save(path)

    def choose_highlight_color(self):
        color = colorchooser.askcolor(color=self.highlight_color, title="Select Highlight Color")
        if color[0]:
            self.highlight_color = tuple(int(c) for c in color[0])
            self._schedule_preview_update()

    def load_gradient_map(self):
        path = filedialog.askopenfilename(filetypes=SUPPORTED_FORMATS)
        if path:
            self.gradient_map_image = Image.open(path).convert('RGB')
            self._schedule_preview_update()

    def load_texture(self):
        path = filedialog.askopenfilename(filetypes=SUPPORTED_FORMATS)
        if path:
            self.texture_image = Image.open(path).convert('RGBA')
            self._schedule_preview_update()

    def set_blend_mode(self, mode):
        self.gradient_blend_mode = mode
        self._schedule_preview_update()

    def reset_adjustments(self):
        self.brightness_factor=1.0; self.invert=False
        self.highlight_color=(255,255,255)
        self.gradient_map_image=None; self.texture_image=None
        self.brightness_var.set(100); self.invert_var.set(False)
        self._schedule_preview_update()

    def toggle_invert(self):
        self.invert_var.set(not self.invert_var.get())
        self._schedule_preview_update()

    def _apply_pipeline(self, img: Image.Image) -> Image.Image:
        out = img
        # Luminance
        out = ImageEnhance.Brightness(out).enhance(self.brightness_var.get()/100.0)
        # Invert
        if self.invert_var.get(): out = invert_image_keep_alpha(out)
        # Highlight overlay
        overlay = Image.new('RGBA', out.size, self.highlight_color + (0,))
        mask = out.convert('L').point(lambda p: max(0,p-128)*2)
        overlay.putalpha(mask)
        out = Image.alpha_composite(out.convert('RGBA'), overlay)
        # Gradient map
        if self.gradient_map_image:
            grad = self.gradient_map_image.resize(out.size)
            out = blend_images(out.convert('RGB'), grad, self.gradient_blend_mode)
        # Texture overlay
        if self.texture_image:
            tex = self.texture_image.resize(out.size)
            out = Image.alpha_composite(out.convert('RGBA'), tex)
        return out

    def _apply_fullres(self):
        if self.original_image is None: return
        self.processed_fullres = self._apply_pipeline(self.original_image)
        self._update_preview()

    def _update_preview(self, preview_img=None):
        if preview_img is None: preview_img = self.processed_fullres
        if preview_img is None: return
        canvas_w = max(1,self.canvas.winfo_width()); canvas_h = max(1,self.canvas.winfo_height())
        iw,ih = preview_img.size
        scale = min(canvas_w/iw, canvas_h/ih,1.0)
        new_w,new_h=max(1,int(iw*scale)),max(1,int(ih*scale))
        preview = preview_img if (new_w==iw and new_h==ih) else preview_img.resize((new_w,new_h),Image.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(preview)
        self.canvas.delete("all")
        self.canvas.create_image(canvas_w//2,canvas_h//2,image=self.preview_photo,anchor=tk.CENTER)
        self.brightness_value_lbl.config(text=f"{int(self.brightness_var.get())}%")

    def _schedule_preview_update(self,delay_ms=50):
        if self.preview_after_id: self.root.after_cancel(self.preview_after_id)
        self.preview_after_id = self.root.after(delay_ms,self._apply_fullres)

def main():
    root=tk.Tk()
    app=ImageEditorApp(root)
    root.mainloop()

if __name__=="__main__": main()
