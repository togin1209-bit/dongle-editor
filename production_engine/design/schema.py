"""
design/schema.py
-------------------
v1.5 작업지시서 5/6/7번: Product Template / Element Asset / Mockup Data 스키마.

**범위 명시**: 여기서는 Backend 데이터 계약(dataclass + 저장/조회 인터페이스)만 설계한다.
- Frontend 에디터(캔버스 편집 UI)는 Gemini 담당이므로 건드리지 않는다.
- 3D Mockup 뷰어 UI 는 구현하지 않는다 - MockupData 는 "Frontend 3D 엔진이 필요로 하는
  데이터가 어떤 모양이어야 하는지"에 대한 계약일 뿐이다.

세 스키마 모두 같은 패턴을 따른다:
  1) 불변 데이터 계약(dataclass) - Frontend/GPT가 이 구조로 주고받는다.
  2) JSON 파일 기반의 가벼운 Repository - Product Profile 과 동일하게, 나중에 DB로
     교체해도 이 인터페이스만 유지하면 호출부는 수정할 필요가 없다.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ============================================================
# 5. Product Template Schema (배너/현수막 디자인 템플릿)
# ============================================================

@dataclass
class DesignTemplate:
    """
    배너/현수막 등 상품에 대해 미리 만들어둔 디자인 템플릿.
    canvas_json 은 프론트엔드 에디터(fabric.js 등)가 그대로 읽어 캔버스에 로드할 수 있는
    직렬화된 캔버스 상태를 담는다 - 이 필드의 *내부 구조*는 에디터(Gemini) 소관이며,
    Backend 는 이를 불투명한(opaque) JSON 으로 그대로 저장/전달만 한다.
    """

    template_id: str
    product_id: str                      # 어떤 상품(taxonomy product_id)에 쓰이는 템플릿인지
    name: str
    industry: Optional[str] = None       # 예: "요식업", "부동산", "학원" 등 업종 태그
    purpose: Optional[str] = None        # 예: "세일", "오픈안내", "구인공고"
    style: Optional[str] = None          # 예: "미니멀", "화려한", "손글씨"
    orientation: str = "landscape"       # "landscape" | "portrait" | "square"
    canvas_width_mm: float = 0.0
    canvas_height_mm: float = 0.0
    thumbnail: Optional[str] = None      # 썸네일 이미지 경로 또는 URL
    canvas_json: dict = field(default_factory=dict)  # 에디터가 정의하는 캔버스 직렬화 데이터 (opaque)
    tags: list[str] = field(default_factory=list)
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def new(product_id: str, name: str, **kwargs) -> "DesignTemplate":
        return DesignTemplate(template_id=str(uuid.uuid4()), product_id=product_id, name=name, **kwargs)


class TemplateRepository:
    """JSON 파일 기반 템플릿 저장소. 파일 하나 = 템플릿 하나 (product_profiles/ 패턴과 동일)."""

    def __init__(self, directory: str):
        self.directory = directory
        os.makedirs(self.directory, exist_ok=True)

    def _path(self, template_id: str) -> str:
        return os.path.join(self.directory, f"{template_id}.json")

    def save(self, template: DesignTemplate) -> str:
        template.updated_at = datetime.now(timezone.utc).isoformat()
        path = self._path(template.template_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(template.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    def get(self, template_id: str) -> Optional[DesignTemplate]:
        path = self._path(template_id)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return DesignTemplate(**raw)

    def list_all(self) -> list[DesignTemplate]:
        if not os.path.isdir(self.directory):
            return []
        out = []
        for filename in sorted(os.listdir(self.directory)):
            if filename.endswith(".json"):
                with open(os.path.join(self.directory, filename), "r", encoding="utf-8") as f:
                    out.append(DesignTemplate(**json.load(f)))
        return out

    def list_by_product(self, product_id: str) -> list[DesignTemplate]:
        return [t for t in self.list_all() if t.product_id == product_id]

    def list_by_tag(self, tag: str) -> list[DesignTemplate]:
        return [t for t in self.list_all() if tag in t.tags]

    def delete(self, template_id: str) -> bool:
        path = self._path(template_id)
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False


# ============================================================
# 6. Element Asset Schema (SVG/PNG 요소 라이브러리)
# ============================================================

@dataclass
class ElementAsset:
    """
    에디터에서 드래그&드롭으로 쓸 수 있는 개별 그래픽 요소(아이콘, 일러스트, 프레임 등).
    실제 SVG/PNG 파일 자체는 file_path 가 가리키는 위치에 별도 저장되고, 이 dataclass는
    그 파일의 메타데이터만 관리한다 (파일 저장소 자체는 GPT 통합 시 CDN/오브젝트 스토리지로
    교체 가능하도록 file_path 를 "논리 경로/URL 문자열"로만 다룬다).
    """

    asset_id: str
    category: str                        # 예: "icon", "illustration", "frame", "pattern"
    subcategory: Optional[str] = None    # 예: "food", "shapes", "arrows"
    style: Optional[str] = None          # 예: "flat", "outline", "3d", "hand-drawn"
    format: str = "svg"                  # "svg" | "png"
    tags: list[str] = field(default_factory=list)
    color_editable: bool = False         # SVG의 fill/stroke 를 에디터에서 색상 변경 가능한지
    license: Optional[str] = None        # 예: "CC0", "royalty-free", "internal"
    file_path: str = ""                  # 실제 파일 경로 또는 URL
    thumbnail: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def new(category: str, file_path: str, **kwargs) -> "ElementAsset":
        return ElementAsset(asset_id=str(uuid.uuid4()), category=category, file_path=file_path, **kwargs)


class ElementAssetRepository:
    """JSON 파일 기반 에셋 메타데이터 저장소."""

    def __init__(self, directory: str):
        self.directory = directory
        os.makedirs(self.directory, exist_ok=True)

    def _path(self, asset_id: str) -> str:
        return os.path.join(self.directory, f"{asset_id}.json")

    def save(self, asset: ElementAsset) -> str:
        path = self._path(asset.asset_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asset.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    def get(self, asset_id: str) -> Optional[ElementAsset]:
        path = self._path(asset_id)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return ElementAsset(**json.load(f))

    def list_all(self) -> list[ElementAsset]:
        if not os.path.isdir(self.directory):
            return []
        out = []
        for filename in sorted(os.listdir(self.directory)):
            if filename.endswith(".json"):
                with open(os.path.join(self.directory, filename), "r", encoding="utf-8") as f:
                    out.append(ElementAsset(**json.load(f)))
        return out

    def list_by_category(self, category: str) -> list[ElementAsset]:
        return [a for a in self.list_all() if a.category == category]

    def search_by_tag(self, tag: str) -> list[ElementAsset]:
        return [a for a in self.list_all() if tag in a.tags]


# ============================================================
# 7. Mockup Data Schema (Frontend 3D Mockup Engine용 데이터 계약)
# ============================================================

@dataclass
class MockupCamera:
    position: list[float] = field(default_factory=lambda: [0.0, 0.0, 5.0])  # [x, y, z]
    target: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    fov_deg: float = 45.0


@dataclass
class MockupLighting:
    type: str = "environment"    # "environment" | "directional" | "point"
    intensity: float = 1.0
    color: str = "#ffffff"
    environment_map: Optional[str] = None  # HDRI 등 환경맵 경로 (type="environment"일 때)


@dataclass
class MockupData:
    """
    Frontend 3D Mockup 엔진(Three.js 등, Gemini 담당)이 렌더링에 필요로 하는 데이터 계약.
    **이 dataclass 는 데이터 구조만 정의하며, 실제 3D 렌더링/뷰어 UI는 구현하지 않는다**
    (작업지시서 7번 명시 사항).

    - model_path: 3D 모델 파일(GLTF/GLB 등) 경로. Backend는 파일을 저장/서빙만 하고,
      로더/렌더러는 Frontend 소관이다.
    - design_surface: 디자인(Production PDF/이미지)이 입혀질 3D 모델 상의 표면 식별자
      (예: 모델의 메쉬 이름 "banner_front_mesh"). 여러 면이 있는 상품(양면 배너 등)은
      surface 별로 별도의 MockupData 를 두거나 design_surfaces 리스트로 확장 가능.
    - uv_mapping: 디자인 이미지를 3D 표면에 입힐 때 사용할 UV 좌표계 정보. 정확한 값은
      3D 모델 제작 시점에 결정되므로 여기서는 참조 정보(어떤 UV 채널/오프셋/스케일을
      쓰는지)만 구조로 담는다.
    """

    product_id: str
    model_path: str
    design_surface: str
    uv_mapping: dict = field(default_factory=lambda: {"channel": 0, "offset": [0.0, 0.0], "scale": [1.0, 1.0], "rotation_deg": 0.0})
    material: dict = field(default_factory=lambda: {"base_color_texture_slot": "diffuse", "roughness": 0.6, "metalness": 0.0})
    scene: Optional[str] = None          # 배경 씬 프리셋 식별자 (예: "studio", "outdoor_street")
    camera: MockupCamera = field(default_factory=MockupCamera)
    lighting: MockupLighting = field(default_factory=MockupLighting)
    environment: Optional[str] = None    # 환경(장소) 프리셋 식별자 - scene과 별개로 배경/반사 등에 사용
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(raw: dict) -> "MockupData":
        raw = dict(raw)
        if "camera" in raw and isinstance(raw["camera"], dict):
            raw["camera"] = MockupCamera(**raw["camera"])
        if "lighting" in raw and isinstance(raw["lighting"], dict):
            raw["lighting"] = MockupLighting(**raw["lighting"])
        return MockupData(**raw)


class MockupDataRepository:
    """JSON 파일 기반 Mockup 데이터 저장소. product_id 당 1개 파일이 기본이지만
    design_surface 가 다르면 별도 파일(예: product_id__surface.json)로 관리 가능하다."""

    def __init__(self, directory: str):
        self.directory = directory
        os.makedirs(self.directory, exist_ok=True)

    def _path(self, product_id: str, design_surface: Optional[str] = None) -> str:
        key = product_id if not design_surface else f"{product_id}__{design_surface}"
        return os.path.join(self.directory, f"{key}.json")

    def save(self, mockup: MockupData) -> str:
        path = self._path(mockup.product_id, mockup.design_surface)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mockup.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    def get(self, product_id: str, design_surface: Optional[str] = None) -> Optional[MockupData]:
        path = self._path(product_id, design_surface)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return MockupData.from_dict(json.load(f))

    def list_for_product(self, product_id: str) -> list[MockupData]:
        if not os.path.isdir(self.directory):
            return []
        out = []
        prefix = f"{product_id}__"
        for filename in sorted(os.listdir(self.directory)):
            if not filename.endswith(".json"):
                continue
            if filename == f"{product_id}.json" or filename.startswith(prefix):
                with open(os.path.join(self.directory, filename), "r", encoding="utf-8") as f:
                    out.append(MockupData.from_dict(json.load(f)))
        return out
