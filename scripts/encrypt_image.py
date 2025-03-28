
import base64
import io
from pathlib import Path
from modules import shared,script_callbacks,scripts as md_scripts,images
from modules.api import api
from modules.shared import opts
from scripts.core.core import decrypt_image_v3, encrypt_image_v3, get_sha256,decrypt_image,decrypt_image_v2,encrypt_image_v2
from PIL import PngImagePlugin,_util,ImagePalette
from PIL import Image as PILImage
from io import BytesIO
from typing import Optional
from fastapi import FastAPI
from gradio import Blocks
from fastapi import FastAPI, Request, Response
import sys
from urllib.parse import unquote

repo_dir = md_scripts.basedir()
password = getattr(shared.cmd_opts, 'enc_pw', None)
api_enable = getattr(shared.cmd_opts, 'api', False)
webp_enable = getattr(shared.cmd_opts, 'enable_webp', False)


def hook_http_request(app: FastAPI):
    @app.middleware("http")
    async def image_dencrypt(req: Request, call_next):
        endpoint:str = req.scope.get('path', 'err')
        endpoint='/'+endpoint.strip('/')
        # 兼容无边浏览器
        if endpoint.startswith('/infinite_image_browsing/image-thumbnail') or endpoint.startswith('/infinite_image_browsing/file'):
            query_string:str = req.scope.get('query_string').decode('utf-8')
            query_string = unquote(query_string)
            if query_string and query_string.index('path=')>=0:
                query = query_string.split('&')
                path = ''
                for sub in query:
                    if sub.startswith('path='):
                        path = sub[sub.index('=')+1:]
                if path:
                    endpoint = '/file=' + path
        # 模型预览图
        if endpoint.startswith('/sd_extra_networks/thumb'):
            query_string:str = req.scope.get('query_string').decode('utf-8')
            query_string = unquote(query_string)
            if query_string and query_string.index('filename=')>=0:
                query = query_string.split('&')
                path = ''
                for sub in query:
                    if sub.startswith('filename='):
                        path = sub[sub.index('=')+1:]
                if path:
                    endpoint = '/file=' + path
        if endpoint.startswith('/file='):
            file_path = endpoint[6:] or ''
            if not file_path: return await call_next(req)
            if file_path.rfind('.') == -1: return await call_next(req)
            if not file_path[file_path.rfind('.'):]: return await call_next(req)
            if file_path[file_path.rfind('.'):].lower() in ['.png','.jpg','.jpeg','.webp','.abcd']:
                image = PILImage.open(file_path)
                pnginfo = image.info or {}
                if 'Encrypt' in pnginfo:
                    buffered = BytesIO()
                    info = PngImagePlugin.PngInfo()
                    for key in pnginfo.keys():
                        if pnginfo[key]:
                            info.add_text(key,pnginfo[key])
                    if(webp_enable):
                        image.save(buffered, format="WebP", quality=100)
                        pic_format = "webp"
                    else:
                        image.save(buffered, format=PngImagePlugin.PngImageFile.format, pnginfo=info)
                        pic_format = "png"
                    decrypted_image_data = buffered.getvalue()
                    response: Response = Response(content=decrypted_image_data, media_type=f"image/{pic_format}")
                    return response
        
        return await call_next(req)
    
def set_shared_options():
    # 传递插件状态到前端
    section = ("encrypt_image_is_enable",'图片加密' if shared.opts.localization == 'zh_CN' else "encrypt image" )
    option = shared.OptionInfo(
            default="是",
            label='是否启用了加密插件' if shared.opts.localization == 'zh_CN' else "Whether the encryption plug-in is enabled",
            section=section,
        )
    option.do_not_save = True
    shared.opts.add_option(
        "encrypt_image_is_enable",
        option,
    )
    shared.opts.data['encrypt_image_is_enable'] = "是"

def app_started_callback(_: Blocks, app: FastAPI):
    set_shared_options()
    if password:
        app.middleware_stack = None  # reset current middleware to allow modifying user provided list
        hook_http_request(app)
        app.build_middleware_stack()  # rebuild middleware stack on-the-fly
    

if PILImage.Image.__name__ != 'EncryptedImage':
    super_open = PILImage.open
    super_encode_pil_to_base64 = api.encode_pil_to_base64
    super_modules_images_save_image = images.save_image
    super_api_middleware = api.api_middleware
    class EncryptedImage(PILImage.Image):
        __name__ = "EncryptedImage"
        
        @staticmethod
        def from_image(image:PILImage.Image):
            image = image.copy()
            img = EncryptedImage()
            img.im = image.im
            img._mode = image.mode
            if image.im.mode:
                try:
                    img.mode = image.im.mode
                except Exception as e:
                    ''
            img._size = image.size
            img.format = image.format
            if image.mode in ("P", "PA"):
                if image.palette:
                    img.palette = image.palette.copy()
                else:
                    img.palette = ImagePalette.ImagePalette()
            img.info = image.info.copy()
            return img
            
        def save(self, fp, format=None, **params):
            filename = ""
            if isinstance(fp, Path):
                filename = str(fp)
            elif _util.is_path(fp):
                filename = fp
            elif fp == sys.stdout:
                try:
                    fp = sys.stdout.buffer
                except AttributeError:
                    pass
            if not filename and hasattr(fp, "name") and _util.is_path(fp.name):
                # only set the name for metadata purposes
                filename = fp.name
            
            if not filename or not password:
                # 如果没有密码或不保存到硬盘，直接保存
                super().save(fp, format = format, **params)
                return
            
            if 'Encrypt' in self.info and (self.info['Encrypt'] == 'pixel_shuffle' or self.info['Encrypt'] == 'pixel_shuffle_2' or self.info['Encrypt'] == 'pixel_shuffle_3'):
                super().save(fp, format = format, **params)
                return
            back_img = PILImage.new('RGBA', self.size)
            back_img.paste(self)
            self.paste(PILImage.fromarray(encrypt_image_v3(self, get_sha256(password))))
            self.format = PngImagePlugin.PngImageFile.format
            pnginfo = params.get('pnginfo', PngImagePlugin.PngInfo())
            if not pnginfo:
                pnginfo = PngImagePlugin.PngInfo()
                for key in (self.info or {}).keys():
                    if self.info[key]:
                        print(f'{key}:{str(self.info[key])}')
                        pnginfo.add_text(key,str(self.info[key]))
            pnginfo.add_text('Encrypt', 'pixel_shuffle_3')
            pnginfo.add_text('EncryptPwdSha', get_sha256(f'{get_sha256(password)}Encrypt'))
            params.update(pnginfo=pnginfo)
            super().save(fp, format=self.format, **params)
            self.paste(back_img)


    def open(fp,*args, **kwargs):
        image = super_open(fp,*args, **kwargs)
        if password and image.format.lower() == PngImagePlugin.PngImageFile.format.lower():
            pnginfo = image.info or {}
            if 'Encrypt' in pnginfo and pnginfo["Encrypt"] == 'pixel_shuffle':
                decrypt_image(image, get_sha256(password))
                pnginfo["Encrypt"] = None
                image = EncryptedImage.from_image(image=image)
                return image
            if 'Encrypt' in pnginfo and pnginfo["Encrypt"] == 'pixel_shuffle_2':
                decrypt_image_v2(image, get_sha256(password))
                pnginfo["Encrypt"] = None
                image = EncryptedImage.from_image(image=image)
                return image
            if 'Encrypt' in pnginfo and pnginfo["Encrypt"] == 'pixel_shuffle_3':
                image.paste(PILImage.fromarray(decrypt_image_v3(image, get_sha256(password))))
                pnginfo["Encrypt"] = None
                image = EncryptedImage.from_image(image=image)
                return image
        return EncryptedImage.from_image(image=image)
    
    def encode_pil_to_base64(image:PILImage.Image):
        with io.BytesIO() as output_bytes:
            pnginfo = image.info or {}
            if 'Encrypt' in pnginfo and pnginfo["Encrypt"] == 'pixel_shuffle':
                decrypt_image(image, get_sha256(password))
                pnginfo["Encrypt"] = None
            if 'Encrypt' in pnginfo and pnginfo["Encrypt"] == 'pixel_shuffle_2':
                decrypt_image_v2(image, get_sha256(password))
                pnginfo["Encrypt"] = None
            if 'Encrypt' in pnginfo and pnginfo["Encrypt"] == 'pixel_shuffle_3':
                image.paste(PILImage.fromarray(decrypt_image_v3(image, get_sha256(password))))
                pnginfo["Encrypt"] = None
            if webp_enable:
                image.save(output_bytes, format="WebP", quality=100)
                print("\noutput webp\n")
            else:
                image.save(output_bytes,format="PNG",quality=opts.jpeg_quality)
                print("\noutput png\n")
            bytes_data = output_bytes.getvalue()
        return base64.b64encode(bytes_data)
  
  
    if password:
        PILImage.Image = EncryptedImage
        PILImage.open = open
        api.encode_pil_to_base64 = encode_pil_to_base64
        
if password:
    script_callbacks.on_app_started(app_started_callback)
    print('图片加密已经启动 加密方式 3')
    # if not api_enable:
    #     print('请添加启动参数 --api，否则不能正常查看图片')

else:
    print('图片加密插件已安装，但缺少密码参数未启动')

if webp_enable:
    print('WebP格式输出已启用')