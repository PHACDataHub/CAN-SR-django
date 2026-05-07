# this file is awkwardly named because it can't start with test_ or it will be picked up by pytest


from bs4 import BeautifulSoup


def get_base_formset_params(prefix):
    return {
        f"{prefix}-TOTAL_FORMS": 0,
        f"{prefix}-INITIAL_FORMS": 0,
    }


def add_prefix(prefix, data):
    return {f"{prefix}-{k}": v for k, v in data.items()}


def add_formset_prefix(form_prefix, index, data):
    return {f"{form_prefix}-{index}-{k}": v for k, v in data.items()}


def soup_from_str(content):
    soup = BeautifulSoup(content, "html.parser")
    return soup
