"""UI module for FileUzi."""

from .widgets import (
    FlowLayout,
    ClickableWordLabel,
    FilingChip,
    AttachmentWidget,
    DropZone,
    DroppableFilesFrame,
)

from .splash import SplashScreen

from .dialogs import (
    SuccessDialog,
    DatabaseMissingDialog,
    DuplicateEmailDialog,
    FileDuplicateDialog,
    DifferentLocationDuplicateDialog,
)

__all__ = [
    # Splash
    'SplashScreen',
    # Widgets
    'FlowLayout',
    'ClickableWordLabel',
    'FilingChip',
    'AttachmentWidget',
    'DropZone',
    'DroppableFilesFrame',
    # Dialogs
    'SuccessDialog',
    'DatabaseMissingDialog',
    'DuplicateEmailDialog',
    'FileDuplicateDialog',
    'DifferentLocationDuplicateDialog',
]
