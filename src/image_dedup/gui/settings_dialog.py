"""Settings dialog — three-tab configuration UI."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, save_config


class SettingsDialog(QDialog):
    """Application settings with Basic / Advanced / Forensics tabs."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._original = config
        self.setWindowTitle("设置")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_basic_tab(), "基本设置")
        self._tabs.addTab(self._build_advanced_tab(), "高级设置")
        self._tabs.addTab(self._build_forensic_tab(), "取证设置")
        layout.addWidget(self._tabs)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_reset = QPushButton("恢复默认")
        btn_reset.clicked.connect(self._on_reset_defaults)
        btn_layout.addWidget(btn_reset)
        btn_layout.addStretch()

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save,
        )
        btn_box.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        btn_layout.addWidget(btn_box)
        layout.addLayout(btn_layout)

        self._load_from_config()

    @property
    def config(self) -> AppConfig:
        return self._config

    # --- Tab builders ---

    def _build_basic_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self._spin_workers = QSpinBox()
        self._spin_workers.setRange(1, 32)
        form.addRow("最大并行线程数:", self._spin_workers)

        self._spin_threshold = QSpinBox()
        self._spin_threshold.setRange(0, 30)
        form.addRow("感知哈希阈值:", self._spin_threshold)

        self._combo_log = QComboBox()
        self._combo_log.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        form.addRow("日志级别:", self._combo_log)

        return tab

    def _build_advanced_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self._spin_orb_features = QSpinBox()
        self._spin_orb_features.setRange(100, 5000)
        form.addRow("ORB 特征数:", self._spin_orb_features)

        self._spin_orb_ratio = QDoubleSpinBox()
        self._spin_orb_ratio.setRange(0.1, 1.0)
        self._spin_orb_ratio.setSingleStep(0.05)
        self._spin_orb_ratio.setDecimals(2)
        form.addRow("ORB 比率阈值:", self._spin_orb_ratio)

        self._spin_feat_min = QDoubleSpinBox()
        self._spin_feat_min.setRange(0.01, 1.0)
        self._spin_feat_min.setSingleStep(0.05)
        self._spin_feat_min.setDecimals(2)
        form.addRow("特征匹配最低分:", self._spin_feat_min)

        self._spin_feat_dim = QSpinBox()
        self._spin_feat_dim.setRange(256, 4096)
        form.addRow("特征匹配最大尺寸:", self._spin_feat_dim)

        self._spin_blend_full = QDoubleSpinBox()
        self._spin_blend_full.setRange(0.0, 1.0)
        self._spin_blend_full.setSingleStep(0.1)
        self._spin_blend_full.setDecimals(2)
        form.addRow("混合比率 (全图):", self._spin_blend_full)

        self._spin_blend_top = QDoubleSpinBox()
        self._spin_blend_top.setRange(0.0, 1.0)
        self._spin_blend_top.setSingleStep(0.1)
        self._spin_blend_top.setDecimals(2)
        form.addRow("混合比率 (顶部):", self._spin_blend_top)

        self._spin_crop = QDoubleSpinBox()
        self._spin_crop.setRange(0.01, 0.50)
        self._spin_crop.setSingleStep(0.01)
        self._spin_crop.setDecimals(2)
        form.addRow("顶部裁剪比例:", self._spin_crop)

        return tab

    def _build_forensic_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self._spin_ela_q = QSpinBox()
        self._spin_ela_q.setRange(1, 100)
        form.addRow("ELA 压缩质量:", self._spin_ela_q)

        self._spin_ela_amp = QDoubleSpinBox()
        self._spin_ela_amp.setRange(1.0, 100.0)
        self._spin_ela_amp.setSingleStep(1.0)
        self._spin_ela_amp.setDecimals(1)
        form.addRow("ELA 放大倍数:", self._spin_ela_amp)

        self._spin_sigma = QDoubleSpinBox()
        self._spin_sigma.setRange(0.1, 10.0)
        self._spin_sigma.setSingleStep(0.5)
        self._spin_sigma.setDecimals(1)
        form.addRow("噪声分析 sigma:", self._spin_sigma)

        self._spin_canny_low = QSpinBox()
        self._spin_canny_low.setRange(1, 300)
        form.addRow("Canny 低阈值:", self._spin_canny_low)

        self._spin_canny_high = QSpinBox()
        self._spin_canny_high.setRange(1, 500)
        form.addRow("Canny 高阈值:", self._spin_canny_high)

        self._spin_forensic_dim = QSpinBox()
        self._spin_forensic_dim.setRange(512, 8192)
        form.addRow("取证最大尺寸:", self._spin_forensic_dim)

        return tab

    # --- Load / Collect ---

    def _load_from_config(self):
        c = self._config
        # Basic
        self._spin_workers.setValue(c.max_workers)
        self._spin_threshold.setValue(c.perceptual_threshold)
        idx = self._combo_log.findText(c.log_level.upper())
        self._combo_log.setCurrentIndex(max(idx, 0))
        # Advanced
        self._spin_orb_features.setValue(c.orb_n_features)
        self._spin_orb_ratio.setValue(c.orb_ratio_threshold)
        self._spin_feat_min.setValue(c.feature_min_score)
        self._spin_feat_dim.setValue(c.feature_max_dim)
        self._spin_blend_full.setValue(c.blend_ratio_full)
        self._spin_blend_top.setValue(c.blend_ratio_top)
        self._spin_crop.setValue(c.top_crop_ratio)
        # Forensics
        self._spin_ela_q.setValue(c.ela_quality)
        self._spin_ela_amp.setValue(c.ela_amplification)
        self._spin_sigma.setValue(c.noise_sigma)
        self._spin_canny_low.setValue(c.canny_low)
        self._spin_canny_high.setValue(c.canny_high)
        self._spin_forensic_dim.setValue(c.forensic_max_dim)

    def _collect_to_config(self) -> AppConfig:
        return AppConfig(
            max_workers=self._spin_workers.value(),
            perceptual_threshold=self._spin_threshold.value(),
            log_level=self._combo_log.currentText(),
            orb_n_features=self._spin_orb_features.value(),
            orb_ratio_threshold=self._spin_orb_ratio.value(),
            feature_min_score=self._spin_feat_min.value(),
            feature_max_dim=self._spin_feat_dim.value(),
            blend_ratio_full=self._spin_blend_full.value(),
            blend_ratio_top=self._spin_blend_top.value(),
            top_crop_ratio=self._spin_crop.value(),
            ela_quality=self._spin_ela_q.value(),
            ela_amplification=self._spin_ela_amp.value(),
            noise_sigma=self._spin_sigma.value(),
            canny_low=self._spin_canny_low.value(),
            canny_high=self._spin_canny_high.value(),
            forensic_max_dim=self._spin_forensic_dim.value(),
        )

    # --- Actions ---

    def _on_reset_defaults(self):
        self._config = AppConfig()
        self._load_from_config()

    def _on_save(self):
        self._config = self._collect_to_config()
        save_config(self._config)
        self.accept()
