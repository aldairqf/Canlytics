from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal as QtSignal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.app_config import get_text
from services.candidate_correlation import CandidateCorrelationCluster


class CandidateCorrelationDialog(QDialog):
    candidate_selected = QtSignal(str)

    def __init__(
        self,
        clusters: Sequence[CandidateCorrelationCluster],
        *,
        threshold: float,
        min_samples: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(get_text("candidate_correlation_title"))
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        note = QLabel(
            get_text("candidate_correlation_threshold_note").format(
                threshold=threshold,
                samples=min_samples,
            ),
            self,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setVisible(bool(clusters))
        layout.addWidget(self.tree, 1)
        if clusters:
            self._populate(clusters)
        else:
            empty = QLabel(get_text("candidate_correlation_empty"), self)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.open_button = QPushButton(get_text("candidate_correlation_select"), self)
        self.open_button.setEnabled(False)
        close_button = QPushButton(get_text("candidate_correlation_close"), self)
        buttons.addWidget(self.open_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.tree.currentItemChanged.connect(self._update_open_enabled)
        self.tree.itemDoubleClicked.connect(lambda item, _column: self._open_item(item))
        self.open_button.clicked.connect(self._open_selected)
        close_button.clicked.connect(self.reject)

    def _populate(self, clusters: Sequence[CandidateCorrelationCluster]) -> None:
        for cluster_index, cluster in enumerate(clusters, start=1):
            root = QTreeWidgetItem(
                [
                    get_text("candidate_correlation_group").format(
                        count=len(cluster.members) + 1,
                        label=cluster.representative.label,
                    )
                ]
            )
            self.tree.addTopLevelItem(root)
            representative = cluster.representative
            representative_item = QTreeWidgetItem(
                [
                    get_text("candidate_correlation_representative").format(
                        label=representative.label,
                    )
                ]
            )
            representative_item.setData(0, Qt.ItemDataRole.UserRole, representative.label)
            root.addChild(representative_item)
            for member in cluster.members:
                item = QTreeWidgetItem(
                    [
                        get_text("candidate_correlation_member").format(
                            label=member.item.label,
                            coefficient=member.coefficient,
                            samples=member.samples,
                        )
                    ]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, member.item.label)
                root.addChild(item)
            root.setExpanded(cluster_index == 1)
        self.tree.resizeColumnToContents(0)

    def _update_open_enabled(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        self.open_button.setEnabled(current is not None and current.data(0, Qt.ItemDataRole.UserRole) is not None)

    def _open_selected(self) -> None:
        current = self.tree.currentItem()
        if current is not None:
            self._open_item(current)

    def _open_item(self, item: QTreeWidgetItem) -> None:
        label = item.data(0, Qt.ItemDataRole.UserRole)
        if label is None:
            return
        self.candidate_selected.emit(str(label))
        self.accept()
