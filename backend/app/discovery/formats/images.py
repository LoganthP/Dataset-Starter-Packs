"""Image datasets, with or without annotations (classification folders, file-name labels, COCO, YOLO,
DOTA, Pascal VOC, LabelMe, simple label CSVs).

Reports image counts, formats, dimensions, class balance, annotation coverage and preview overlays.
Image headers are read without decoding pixels, in batches, so thousands of images stay cheap; only the
preview thumbnails are decoded. A Quick sample takes a systematic sample (every k-th file by name) so
classes sorted by file name are still represented.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from .registry import IMAGE, Handler, Job, register, stem_key

SAMPLE_IMAGES = 500
MAX_ANNOTATION_JSON = 100 * 10**6  # bigger JSON files are data dumps (e.g. shipsnet.json), not label files
SHIPS_NAME = re.compile(r"^(?P<label>[^_/]+)__(?P<scene>[^_]+(?:_[^_]+)*?)__(?P<lon>-?\d+(?:\.\d+)?)_(?P<lat>-?\d+(?:\.\d+)?)\.[A-Za-z]+$")
SPLITS = ("train", "training", "val", "valid", "validation", "test", "testing")


def _is_annotation(m: dict) -> bool:
    n = m["name"].lower()
    if m["type"] == "json":
        return m["size"] <= MAX_ANNOTATION_JSON
    return m["type"] in ("txt", "xml", "yaml") or (m["type"] == "csv" and m["size"] <= 50 * 10**6) or n.endswith(("classes.txt", ".names"))


class Images(Handler):
    key = "images"
    label = "Image dataset"
    types = IMAGE
    description = "Image counts, dimensions, class balance, annotation coverage and preview overlays."

    def score(self, members: list[dict]) -> float:
        imgs = [m for m in members if m["type"] in IMAGE]
        if len(imgs) < 5 and not (imgs and len(imgs) == len(members)):  # a few images alone (one photo) still get an image report
            return 0.0
        useful = sum(1 for m in members if m["type"] in IMAGE or _is_annotation(m))
        return 0.5 + 0.5 * useful / len(members)

    def select(self, members, *, sample, params):
        imgs = sorted((m for m in members if m["type"] in IMAGE), key=lambda m: m["name"])
        if sample and len(imgs) > SAMPLE_IMAGES:
            step = len(imgs) / SAMPLE_IMAGES
            imgs = [imgs[int(i * step)] for i in range(SAMPLE_IMAGES)]
        keys = {stem_key(m["name"]) for m in imgs}
        anns = [m for m in members if _is_annotation(m) and (not sample or stem_key(m["name"]) in keys or _global_annotation(m))]
        return imgs + anns

    def analyze(self, job: Job) -> dict:
        from PIL import Image

        from ..analysis import analyze as profile

        Image.MAX_IMAGE_PIXELS = None  # headers only; previews below are size-checked
        root = job.root
        rel = {p: p.relative_to(root).as_posix() for p in job.paths}
        imgs = sorted([p for p in job.paths if _ext_type(p) in IMAGE], key=lambda p: rel[p])
        anns = [p for p in job.paths if p not in imgs]
        all_imgs = [m for m in job.members if m["type"] in IMAGE] or [{"name": rel[p], "size": p.stat().st_size} for p in imgs]
        labels = Annotations(anns, rel)
        job.log(f"Found {len(all_imgs):,} images and {len(anns):,} annotation/label files; reading {len(imgs):,} image headers"
                + (f" ({labels.format_label})" if labels.format else ""))
        rows, previews = [], []
        name_labels = _filename_labels([rel[p] for p in imgs])
        folder_labels = {} if (name_labels or labels.formats) else _folder_labels([rel[p] for p in imgs])
        for i, p in enumerate(imgs):
            if i % 200 == 0:
                job.cancel()
                job.progress("analyzing", i, len(imgs), "images")
            r = rel[p]
            row = {"file": r, "folder": r.rsplit("/", 1)[0] if "/" in r else "", "split": _split(r), "format": _ext_type(p), "bytes": p.stat().st_size}
            try:
                with Image.open(p) as im:
                    row.update({"width": im.size[0], "height": im.size[1], "mode": im.mode, "bands": len(im.getbands())})
            except Exception as exc:  # noqa: BLE001
                row["read_error"] = f"{type(exc).__name__}"
            objs = labels.objects_for(r)
            cls = labels.image_class(r) or name_labels.get(r) or folder_labels.get(r)
            m = SHIPS_NAME.match(r.rsplit("/", 1)[-1])
            if m:
                row.update({"longitude": float(m.group("lon")), "latitude": float(m.group("lat")), "scene": m.group("scene")})
            row["class"] = cls
            row["objects"] = len(objs) if objs is not None else None
            row["annotated"] = (objs is not None) or cls is not None
            rows.append(row)
        job.progress("analyzing", len(imgs), len(imgs), "images")
        for r in rows:  # previews: prefer images with objects, then labelled ones
            if len(previews) >= 6:
                break
            if labels.has_shapes and not r.get("objects"):
                continue
            pv = _preview(root / r["file"], labels.objects_for(r["file"]) or [], r)
            if pv:
                previews.append(pv)
        table = root / "image_index.csv"
        keys = list(dict.fromkeys(k for r in rows for k in r))
        with open(table, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        report = profile(table, "csv", deadline=job.deadline, on_charts=job.on_charts)
        dims = Counter((r.get("width"), r.get("height")) for r in rows if r.get("width"))
        objects_by_class = labels.objects_by_class([r["file"] for r in rows])
        class_images = Counter(r["class"] for r in rows if r.get("class") is not None)
        with_objects = sum(1 for r in rows if r.get("objects"))
        annotated = sum(1 for r in rows if r["annotated"])
        sample = len(imgs) < len(all_imgs)
        report.update({
            "kind": "images",
            "coverage": "sample" if sample else "full",
            "rows_total": len(all_imgs),
            "sample_method": f"systematic sample: every {len(all_imgs) / max(1, len(imgs)):.0f}th of {len(all_imgs):,} images by file name" if sample else None,
            "images": {
                "total": len(all_imgs), "analyzed": len(rows), "unreadable": sum(1 for r in rows if r.get("read_error")),
                "formats": Counter(r["format"] for r in rows).most_common(),
                "dimensions": [[f"{w}×{h}", c] for (w, h), c in dims.most_common(12)],
                "width": _stats([r["width"] for r in rows if r.get("width")]), "height": _stats([r["height"] for r in rows if r.get("height")]),
                "folders": Counter(r["folder"] or "(top level)" for r in rows).most_common(12),
                "splits": Counter(r["split"] for r in rows if r["split"]).most_common(),
                "annotation_format": labels.format, "annotation_format_label": labels.format_label,
                "label_source": labels.format_label or ("file-name prefix (label__scene__lon_lat)" if name_labels else
                                                        "folder name" if folder_labels else None),
                "annotated": annotated, "annotated_pct": round(100 * annotated / len(rows), 1) if rows else 0,
                "with_objects": with_objects, "objects": sum(r.get("objects") or 0 for r in rows),
                "class_images": class_images.most_common(30), "objects_by_class": objects_by_class.most_common(30),
                "geotagged": sum(1 for r in rows if r.get("latitude") is not None),
                "previews": previews, "unparsed_annotations": labels.unparsed[:10],
            },
        })
        return report


def _global_annotation(m: dict) -> bool:
    n = m["name"].lower().rsplit("/", 1)[-1]
    return m["type"] in ("json", "yaml", "csv") or n in ("classes.txt", "obj.names", "labels.txt") or n.endswith(".names")


def _ext_type(p: Path) -> str:
    from .registry import type_from_name

    return type_from_name(p.name)


def _split(path: str) -> str | None:
    for part in path.lower().split("/")[:-1]:
        if part in SPLITS:
            return {"training": "train", "valid": "val", "validation": "val", "testing": "test"}.get(part, part)
    return None


def _filename_labels(names: list[str]) -> dict[str, str]:
    hits = {n: m.group("label") for n in names if (m := SHIPS_NAME.match(n.rsplit("/", 1)[-1]))}
    return hits if names and len(hits) >= 0.8 * len(names) else {}


def _folder_labels(names: list[str]) -> dict[str, str]:
    """ImageFolder layout: <root>/<class>/<image> with 2-50 classes."""
    parents = {n: n.rsplit("/", 2)[-2] for n in names if n.count("/") >= 1}
    parents = {n: p for n, p in parents.items() if p.lower() not in SPLITS and p.lower() not in ("images", "imgs", "img", "jpegimages")}
    classes = set(parents.values())
    return parents if 2 <= len(classes) <= 50 and len(parents) >= 0.9 * len(names) else {}


def _stats(vals: list[int]) -> dict | None:
    if not vals:
        return None
    v = sorted(vals)
    return {"min": v[0], "median": v[len(v) // 2], "max": v[-1]}


def _preview(path: Path, objs: list[dict], row: dict) -> dict | None:
    from PIL import Image

    try:
        if (row.get("width") or 0) * (row.get("height") or 0) > 60_000_000:
            return None
        with Image.open(path) as im:
            w, h = im.size
            im.draft("RGB", (320, 320))
            im = im.convert("RGB")
            im.thumbnail((320, 320))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=72)
    except Exception:  # noqa: BLE001
        return None
    shapes = []
    for o in objs[:60]:
        pts = o["points"]
        if o.get("normalized"):
            norm = pts
        else:
            norm = [[x / w, y / h] for x, y in pts] if w and h else []
        if norm:
            shapes.append({"label": o.get("label"), "points": [[round(x, 4), round(y, 4)] for x, y in norm]})
    return {"file": row["file"], "width": w, "height": h, "class": row.get("class"), "src": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
            "shapes": shapes}


class Annotations:
    """Reads every annotation file it recognizes and answers per-image questions."""

    def __init__(self, paths: list[Path], rel: dict[Path, str]):
        self.by_image: dict[str, list[dict]] = {}
        self.class_of: dict[str, str] = {}
        self.names: dict[int, str] = {}
        self.formats: Counter = Counter()
        self.unparsed: list[str] = []
        for p in sorted(paths, key=lambda q: rel[q]):  # class name lists first
            n = p.name.lower()
            if n in ("classes.txt", "obj.names", "labels.txt") or n.endswith(".names"):
                self.names = {i: ln.strip() for i, ln in enumerate(p.read_text(errors="replace").splitlines()) if ln.strip()}
            elif n.endswith((".yaml", ".yml")):
                self._yaml_names(p)
        for p in paths:
            n = p.name.lower()
            try:
                if n.endswith(".json"):
                    self._json(p, rel[p])
                elif n.endswith(".xml"):
                    self._voc(p, rel[p])
                elif n.endswith(".txt") and n not in ("classes.txt", "labels.txt", "readme.txt"):
                    self._txt(p, rel[p])
                elif n.endswith(".csv"):
                    self._csv(p)
            except Exception as exc:  # noqa: BLE001 - one bad file never fails the report
                self.unparsed.append(f"{rel[p]}: {type(exc).__name__}")

    format = property(lambda self: self.formats.most_common(1)[0][0] if self.formats else None)
    has_shapes = property(lambda self: any(self.by_image.values()))

    @property
    def format_label(self) -> str | None:
        return {"coco": "COCO JSON", "yolo": "YOLO text", "yolo-obb": "YOLO oriented boxes", "dota": "DOTA oriented boxes (x1 y1 … x4 y4 class)",
                "voc": "Pascal VOC XML", "labelme": "LabelMe JSON polygons", "csv": "label CSV"}.get(self.format or "", None)

    def objects_for(self, image: str) -> list[dict] | None:
        return self.by_image.get(stem_key(image))

    def image_class(self, image: str) -> str | None:
        return self.class_of.get(stem_key(image))

    def objects_by_class(self, images: list[str]) -> Counter:
        c: Counter = Counter()
        for im in images:
            for o in self.by_image.get(stem_key(im)) or []:
                c[o.get("label") or "object"] += 1
        return c

    def _add(self, image: str, obj: dict | None, fmt: str) -> None:
        self.formats[fmt] += 1
        lst = self.by_image.setdefault(stem_key(image), [])
        if obj:
            lst.append(obj)

    def _yaml_names(self, p: Path) -> None:
        text = p.read_text(errors="replace")
        m = re.search(r"names:\s*\[(.*?)\]", text, re.S)
        if m:
            self.names = {i: s.strip().strip("'\"") for i, s in enumerate(m.group(1).split(",")) if s.strip()}
            return
        block = re.search(r"names:\s*\n((?:\s+\d+:\s*.+\n?)+)", text)
        if block:
            self.names = {int(k): v.strip().strip("'\"") for k, v in re.findall(r"(\d+):\s*(.+)", block.group(1))}

    def _label(self, raw) -> str:
        try:
            return self.names.get(int(raw), str(raw))
        except (TypeError, ValueError):
            return str(raw)

    def _json(self, p: Path, rel: str) -> None:
        data = json.loads(p.read_text(errors="replace"))
        if isinstance(data, dict) and "images" in data and "annotations" in data:  # COCO
            cats = {c["id"]: c.get("name", str(c["id"])) for c in data.get("categories", [])}
            files = {im["id"]: im for im in data["images"]}
            for im in data["images"]:
                self._add(im["file_name"], None, "coco")
            for a in data["annotations"]:
                im = files.get(a.get("image_id"))
                if not im:
                    continue
                pts = None
                seg = a.get("segmentation")
                if isinstance(seg, list) and seg and isinstance(seg[0], list) and len(seg[0]) >= 6:
                    pts = list(zip(seg[0][0::2], seg[0][1::2]))
                elif a.get("bbox"):
                    x, y, w, h = a["bbox"][:4]
                    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                if pts:
                    obj = {"label": cats.get(a.get("category_id"), str(a.get("category_id"))), "points": [list(q) for q in pts]}
                    if im.get("width") and im.get("height"):
                        obj = {**obj, "points": [[x / im["width"], y / im["height"]] for x, y in pts], "normalized": True}
                    self._add(im["file_name"], obj, "coco")
        elif isinstance(data, dict) and "shapes" in data:  # LabelMe
            image = data.get("imagePath") or rel
            w, h = data.get("imageWidth"), data.get("imageHeight")
            self._add(image, None, "labelme")
            for s in data["shapes"]:
                pts = s.get("points") or []
                if s.get("shape_type") == "rectangle" and len(pts) == 2:
                    (x1, y1), (x2, y2) = pts
                    pts = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
                obj = {"label": s.get("label"), "points": pts}
                if w and h:
                    obj = {**obj, "points": [[x / w, y / h] for x, y in pts], "normalized": True}
                self._add(image, obj, "labelme")
        else:
            self.unparsed.append(f"{rel}: JSON without COCO or LabelMe structure")

    def _voc(self, p: Path, rel: str) -> None:
        root = ET.parse(p).getroot()
        if root.tag != "annotation":
            self.unparsed.append(f"{rel}: XML is not Pascal VOC")
            return
        image = root.findtext("filename") or rel
        w, h = float(root.findtext("size/width") or 0), float(root.findtext("size/height") or 0)
        self._add(image, None, "voc")
        for o in root.findall("object"):
            bb = o.find("bndbox")
            if bb is not None:
                x1, y1, x2, y2 = (float(bb.findtext(k) or 0) for k in ("xmin", "ymin", "xmax", "ymax"))
                pts = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
                obj = {"label": o.findtext("name"), "points": pts}
                if w and h:
                    obj = {**obj, "points": [[x / w, y / h] for x, y in pts], "normalized": True}
                self._add(image, obj, "voc")

    def _txt(self, p: Path, rel: str) -> None:
        lines = [ln.split() for ln in p.read_text(errors="replace").splitlines() if ln.strip()]
        lines = [ln for ln in lines if not (ln[0].lower().startswith(("imagesource:", "gsd:")))]
        if not lines:
            self._add(rel, None, self.format or "yolo")  # an empty label file means "no objects", which is still an annotation
            return
        for parts in lines:
            nums = []
            for tok in parts:
                try:
                    nums.append(float(tok))
                except ValueError:
                    break
            if len(parts) >= 9 and len(nums) >= 8 and (len(nums) == 8 or len(parts) > len(nums)) and not _is_int_token(parts[0], parts):
                # DOTA: x1 y1 ... x4 y4 class [difficult] in pixels
                self._add(rel, {"label": parts[8], "points": [[nums[i], nums[i + 1]] for i in range(0, 8, 2)]}, "dota")
            elif len(nums) == 5 and all(0 <= v <= 1.0001 for v in nums[1:]):
                _, cx, cy, w, h = nums
                self._add(rel, {"label": self._label(int(nums[0])), "normalized": True,
                                "points": [[cx - w / 2, cy - h / 2], [cx + w / 2, cy - h / 2], [cx + w / 2, cy + h / 2], [cx - w / 2, cy + h / 2]]}, "yolo")
            elif len(nums) >= 7 and len(nums) % 2 == 1 and all(0 <= v <= 1.0001 for v in nums[1:]):
                self._add(rel, {"label": self._label(int(nums[0])), "normalized": True,
                                "points": [[nums[i], nums[i + 1]] for i in range(1, len(nums) - 1, 2)]}, "yolo-obb")
            else:
                self.unparsed.append(f"{rel}: unrecognized line '{' '.join(parts)[:60]}'")
                return

    def _csv(self, p: Path) -> None:
        with open(p, newline="", errors="replace") as fh:
            reader = csv.DictReader(fh)
            cols = {c.lower(): c for c in reader.fieldnames or []}
            fcol = next((cols[c] for c in ("filename", "file_name", "file", "image", "image_id", "path", "id") if c in cols), None)
            lcol = next((cols[c] for c in ("label", "class", "category", "target", "class_name") if c in cols), None)
            if not (fcol and lcol):
                return
            box = [cols.get(k) for k in ("xmin", "ymin", "xmax", "ymax")]
            for r in reader:
                if all(box):
                    try:
                        x1, y1, x2, y2 = (float(r[k]) for k in box)
                        self._add(r[fcol], {"label": r[lcol], "points": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]}, "csv")
                        continue
                    except ValueError:
                        pass
                self.class_of[stem_key(r[fcol])] = r[lcol]
                self.formats["csv"] += 1


def _is_int_token(tok: str, parts: list[str]) -> bool:
    """YOLO polygons start with an integer class id and have only numbers; DOTA has the class name 9th."""
    return tok.isdigit() and all(re.fullmatch(r"-?\d+(\.\d+)?(e-?\d+)?", t) for t in parts)


register(Images())
