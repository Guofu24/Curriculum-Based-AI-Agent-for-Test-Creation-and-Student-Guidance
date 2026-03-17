from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

converter = PdfConverter(
    artifact_dict=create_model_dict(),
)
rendered = converter("E:\\Đồ án\\Project\\sach-giao-khoa-giai-tich-12-co-ban.pdf")
text, _, images = text_from_rendered(rendered)