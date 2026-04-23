from proj.htpy.modal_base import ModalComponent


def test_modal_component_allows_disabling_outside_click_close():
    content = str(
        ModalComponent(
            title="Test modal",
            close_on_outside_click=False,
        )["Body"]
    )

    assert 'data-modal-close-on-outside-click="false"' in content


def test_modal_component_closes_on_outside_click_by_default():
    content = str(ModalComponent(title="Test modal")["Body"])

    assert 'data-modal-close-on-outside-click="false"' not in content
