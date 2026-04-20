"""Settings dialog — multi-tab configuration UI."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QApplication,
)

from ..config import AppConfig, save_config
from .theme import apply_theme


class SettingsDialog(QDialog):
    """Application settings with multiple tabs."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._original = config
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_basic_tab(), "基本设置")
        self._tabs.addTab(self._build_advanced_tab(), "高级设置")
        self._tabs.addTab(self._build_forensic_tab(), "取证设置")
        self._tabs.addTab(self._build_system_tab(), "系统设置")
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
        layout = QVBoxLayout(tab)

        # Appearance
        appearance_group = QGroupBox("外观")
        appearance_form = QFormLayout(appearance_group)
        self._combo_theme = QComboBox()
        self._combo_theme.addItems(["浅色", "深色"])
        appearance_form.addRow("主题:", self._combo_theme)
        layout.addWidget(appearance_group)

        # Performance
        perf_group = QGroupBox("性能")
        perf_form = QFormLayout(perf_group)
        self._spin_workers = QSpinBox()
        self._spin_workers.setRange(1, 32)
        perf_form.addRow("最大并行线程数:", self._spin_workers)

        self._spin_threshold = QSpinBox()
        self._spin_threshold.setRange(0, 30)
        perf_form.addRow("感知哈希阈值:", self._spin_threshold)

        self._check_gpu = QCheckBox("启用 GPU 加速（需要 CUDA）")
        perf_form.addRow("", self._check_gpu)

        self._spin_batch_size = QSpinBox()
        self._spin_batch_size.setRange(1000, 100000)
        self._spin_batch_size.setSingleStep(1000)
        perf_form.addRow("扫描批次大小:", self._spin_batch_size)

        layout.addWidget(perf_group)
        layout.addStretch()
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

        # Video settings
        self._spin_video_interval = QDoubleSpinBox()
        self._spin_video_interval.setRange(0.5, 10.0)
        self._spin_video_interval.setSingleStep(0.5)
        self._spin_video_interval.setDecimals(1)
        form.addRow("视频关键帧间隔(秒):", self._spin_video_interval)

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

    def _build_system_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # System
        sys_group = QGroupBox("系统")
        sys_form = QFormLayout(sys_group)

        self._combo_log = QComboBox()
        self._combo_log.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        sys_form.addRow("日志级别:", self._combo_log)

        self._check_tray = QCheckBox("最小化到系统托盘")
        sys_form.addRow("", self._check_tray)

        self._check_extract_archive_dir = QCheckBox("解压到压缩包所在目录")
        sys_form.addRow("", self._check_extract_archive_dir)

        layout.addWidget(sys_group)

        # Batch operations
        batch_group = QGroupBox("批量操作")
        batch_form = QFormLayout(batch_group)

        self._edit_batch_move_dir = QLineEdit()
        self._edit_batch_move_dir.setPlaceholderText("留空则每次询问")
        batch_form.addRow("默认移动目录:", self._edit_batch_move_dir)

        self._check_auto_keep_best = QCheckBox("自动保留最优文件")
        batch_form.addRow("", self._check_auto_keep_best)

        self._edit_rename_pattern = QLineEdit()
        batch_form.addRow("重命名模式:", self._edit_rename_pattern)

        layout.addWidget(batch_group)
        layout.addStretch()
        return tab

    # --- Load / Collect ---

    def _load_from_config(self):
        c = self._config
        # Basic
        self._combo_theme.setCurrentIndex(0 if c.theme == "light" else 1)
        self._spin_workers.setValue(c.max_workers)
        self._spin_threshold.setValue(c.perceptual_threshold)
        self._check_gpu.setChecked(c.gpu_acceleration)
        self._spin_batch_size.setValue(c.scan_batch_size)

        # Advanced
        self._spin_orb_features.setValue(c.orb_n_features)
        self._spin_orb_ratio.setValue(c.orb_ratio_threshold)
        self._spin_feat_min.setValue(c.feature_min_score)
        self._spin_feat_dim.setValue(c.feature_max_dim)
        self._spin_blend_full.setValue(c.blend_ratio_full)
        self._spin_blend_top.setValue(c.blend_ratio_top)
        self._spin_crop.setValue(c.top_crop_ratio)
        self._spin_video_interval.setValue(c.video_keyframe_interval)

        # Forensics
        self._spin_ela_q.setValue(c.ela_quality)
        self._spin_ela_amp.setValue(c.ela_amplification)
        self._spin_sigma.setValue(c.noise_sigma)
        self._spin_canny_low.setValue(c.canny_low)
        self._spin_canny_high.setValue(c.canny_high)
        self._spin_forensic_dim.setValue(c.forensic_max_dim)

        # System
        idx = self._combo_log.findText(c.log_level.upper())
        self._combo_log.setCurrentIndex(max(idx, 0))
        self._check_tray.setChecked(c.minimize_to_tray)
        self._check_extract_archive_dir.setChecked(c.extract_to_archive_dir)
        self._edit_batch_move_dir.setText(c.batch_move_dir)
        self._check_auto_keep_best.setChecked(c.auto_keep_best)
        self._edit_rename_pattern.setText(c.batch_rename_pattern)

    def _collect_to_config(self) -> AppConfig:
        new_config = AppConfig(
            # Basic
            theme="light" if self._combo_theme.currentIndex() == 0 else "dark",
            max_workers=self._spin_workers.value(),
            perceptual_threshold=self._spin_threshold.value(),
            gpu_acceleration=self._check_gpu.isChecked(),
            scan_batch_size=self._spin_batch_size.value(),
            # Advanced
            orb_n_features=self._spin_orb_features.value(),
            orb_ratio_threshold=self._spin_orb_ratio.value(),
            feature_min_score=self._spin_feat_min.value(),
            feature_max_dim=self._spin_feat_dim.value(),
            blend_ratio_full=self._spin_blend_full.value(),
            blend_ratio_top=self._spin_blend_top.value(),
            top_crop_ratio=self._spin_crop.value(),
            video_keyframe_interval=self._spin_video_interval.value(),
            # Forensics
            ela_quality=self._spin_ela_q.value(),
            ela_amplification=self._spin_ela_amp.value(),
            noise_sigma=self._spin_sigma.value(),
            canny_low=self._spin_canny_low.value(),
            canny_high=self._spin_canny_high.value(),
            forensic_max_dim=self._spin_forensic_dim.value(),
            # System
            log_level=self._combo_log.currentText(),
            minimize_to_tray=self._check_tray.isChecked(),
            extract_to_archive_dir=self._check_extract_archive_dir.isChecked(),
            batch_move_dir=self._edit_batch_move_dir.text(),
            auto_keep_best=self._check_auto_keep_best.isChecked(),
            batch_rename_pattern=self._edit_rename_pattern.text(),
            # Preserve other fields from original config
            video_phash_threshold=self._config.video_phash_threshold,
            semantic_enabled=self._config.semantic_enabled,
            semantic_model=self._config.semantic_model,
            semantic_threshold=self._config.semantic_threshold,
            cross_doc_enabled=self._config.cross_doc_enabled,
            resume_scan_enabled=self._config.resume_scan_enabled,
            scheduled_scan_enabled=self._config.scheduled_scan_enabled,
            scheduled_scan_interval_min=self._config.scheduled_scan_interval_min,
            scheduled_scan_paths=self._config.scheduled_scan_paths,
            file_watcher_enabled=self._config.file_watcher_enabled,
            file_watcher_paths=self._config.file_watcher_paths,
            heic_enabled=self._config.heic_enabled,
            avif_enabled=self._config.avif_enabled,
        )
        return new_config

    # --- Actions ---

    def _on_reset_defaults(self):
        self._config = AppConfig()
        self._load_from_config()

    def _on_save(self):
        old_theme = self._config.theme
        self._config = self._collect_to_config()
        save_config(self._config)

        # Apply theme if changed
        if self._config.theme != old_theme:
            app = QApplication.instance()
            if app:
                apply_theme(app, self._config.theme)

        self.accept()
