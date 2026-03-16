import argparse
import tempfile
import zipfile
import logging
import warnings
from pathlib import Path
from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from enum import Enum


class Format(Enum):
    EPUB = ".epub"
    AZW3 = ".azw3"


# ---------------------------------------------------------------------------
# Fixing image tags.
# ---------------------------------------------------------------------------


def get_image_src(image_tag: Tag) -> str | None:
    """Extract the image path in <image> tag."""
    return image_tag.get("xlink:href") or image_tag.get("href") or image_tag.get("src")


def image_tag_to_img(image_tag: Tag, soup: BeautifulSoup) -> Tag:
    """Convert a single <image> tag to <img src="...">.
    Drops all original attributes."""
    src = get_image_src(image_tag)
    img = soup.new_tag(
        "img",
        attrs={
            "max-width": "100%",
            "max-height": "100%",
        },
    )
    if src:
        img["src"] = src
    return img


def collect_img_tags(svg_tag: Tag, soup: BeautifulSoup) -> list[Tag]:
    """Find all <image> children (at any depth) inside an svg and convert
    each to custom <img> tag."""
    return [image_tag_to_img(image, soup) for image in svg_tag.find_all("image")]


def svg_tag_to_p(svg_tag: Tag, soup: BeautifulSoup) -> Tag:
    """Replace an <svg> tag with <p> containing converted <img> children."""
    p = soup.new_tag("p")
    for img in collect_img_tags(svg_tag, soup):
        p.append(img)
    return p


# ---------------------------------------------------------------------------
# Fixing RTL
# ---------------------------------------------------------------------------

_METADATA = "metadata"
_META = "meta"
_NAME = "name"
_PRIMARY_WRITING_MODE = "primary-writing-mode"


def _primary_writing_mode_defined(metadata: Tag) -> bool:
    """Returns whether primary writing mode is defined in metadata."""
    for meta in metadata.find_all(_META):
        if meta.get(_NAME) == _PRIMARY_WRITING_MODE:
            return True
    return False


def add_rtl_metadata(soup: BeautifulSoup) -> None:
    _CONTENT = "content"
    _VERTICAL_RTL = "vertical-rl"
    for metadata in soup.find_all(_METADATA):
        if _primary_writing_mode_defined(metadata):
            continue
        logging.debug(
            "Found <metadata> without primary writing mode. Adding RTL <meta> tag."
        )
        metadata.append(
            soup.new_tag(
                _META,
                attrs={
                    _NAME: _PRIMARY_WRITING_MODE,
                    _CONTENT: _VERTICAL_RTL,
                },
            )
        )


# ---------------------------------------------------------------------------
# Document-level transform
# ---------------------------------------------------------------------------


def fix_svg_elements(soup: BeautifulSoup) -> None:
    """Find every <svg> in the document and replace it in-place with a <p>."""
    for svg in soup.find_all("svg"):
        svg.replace_with(svg_tag_to_p(svg, soup))


def parse_xhtml(content: bytes) -> BeautifulSoup:
    """Parse xhtml/html bytes into a BeautifulSoup tree."""
    return BeautifulSoup(content, features="html.parser")


def parse_opf(content: bytes) -> BeautifulSoup:
    return BeautifulSoup(content, features="html.parser")


def serialize_to_utf8(soup: BeautifulSoup) -> bytes:
    """Serialize a BeautifulSoup tree back to bytes."""
    return str(soup).encode("utf-8")


def process_xhtml_file(content: bytes) -> bytes:
    """Full pipeline for a single xhtml file: parse -> fix -> serialize."""
    soup = parse_xhtml(content)
    fix_svg_elements(soup)
    return serialize_to_utf8(soup)


def process_opf_file(content: bytes) -> bytes:
    soup = parse_opf(content)
    add_rtl_metadata(soup)
    return serialize_to_utf8(soup)


# ---------------------------------------------------------------------------
# File-system helpers
# ---------------------------------------------------------------------------


def is_xhtml_file(path: Path) -> bool:
    return path.suffix.lower() in (".xhtml", ".html", ".htm")


def file_contains_svg(content: bytes) -> bool:
    return b"<svg" in content


def process_xhtml_in_dir(directory: Path) -> None:
    """Walk a directory tree and fix every xhtml file that contains svg."""
    for fpath in directory.rglob("*"):
        if not fpath.is_file():
            continue
        if not is_xhtml_file(fpath):
            continue
        content = fpath.read_bytes()
        if not file_contains_svg(content):
            continue
        fpath.write_bytes(process_xhtml_file(content))


def fix_rtl_in_dir(directory: Path) -> None:
    for fpath in directory.rglob("*.opf"):
        if not fpath.is_file():
            continue
        logging.debug(f"Processing OPF file: {fpath}")
        content = fpath.read_bytes()
        b = process_opf_file(content)
        fpath.write_bytes(b)


# ---------------------------------------------------------------------------
# Epub zip/unzip
# ---------------------------------------------------------------------------


def unzip_epub(epub_path: Path, dest_dir: Path) -> None:
    with zipfile.ZipFile(epub_path, "r") as z:
        z.extractall(dest_dir)


def rezip_epub(src_dir: Path, output_path: Path) -> None:
    """Repack a directory into an epub.
    mimetype must be first entry and stored uncompressed per the epub spec."""
    mimetype_path = src_dir / "mimetype"
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
        if mimetype_path.exists():
            zout.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
        for fpath in src_dir.rglob("*"):
            if not fpath.is_file():
                continue
            arcname = fpath.relative_to(src_dir)
            if arcname == Path("mimetype"):
                continue
            zout.write(fpath, arcname)


def fixed_epub_path(input_path: Path) -> Path:
    return input_path.with_stem(input_path.stem + "_fixed")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def fix_epub(
    input_epub_file_path: str | Path, output_epub_file_path: str | Path, fix_rtl: bool
) -> Path:
    """Convert input to epub if needed, then fix it by replacing <svg>
    elements with <p class="calibre"> and converting inner
    <image xlink:href="..."> to <img src="...">.

    Args:
        input_epub_file_path: Path to the input epub file
        output_epub_file_path: Path to the output epub file

    Returns:
        Path to the fixed epub.
    """
    input_path = Path(input_epub_file_path)
    output_path = Path(output_epub_file_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        unzip_epub(input_path, tmp / "unpacked")
        process_xhtml_in_dir(tmp / "unpacked")
        if fix_rtl:
            fix_rtl_in_dir(tmp / "unpacked")

        rezip_epub(tmp / "unpacked", output_path)

    print(f"Fixed epub written to: {output_path}")
    return output_path


def handle_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", required=True, help="Path to the ebook file")
    parser.add_argument("-o", "--output", required=True, help="Output file path")
    parser.add_argument(
        "--fix-rtl",
        help=(
            "Makes an attempt to fix right-to-left text books layout. "
            "For some books, Because the glyphs are vertical, the text might appear vertical "
            "already and the sentences "
            "are also aligned left-to-right. However, the layout is horizontal. You see this "
            "if the book has very little horizontal margin but rather big default vertical margin."
        ),
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = handle_args()
    # OPF is xml but the BS4 parser is not used to validate it, so just ignore the warning.
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    fix_epub(args.input, args.output, args.fix_rtl)
