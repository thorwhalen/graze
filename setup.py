from setuptools import setup

setup()  # Note: Everything should be in the local setup.cfg

# from setuptools import setup
# import os
# from typing import Mapping, Union, Iterable, Generator
# from configparser import ConfigParser
# import re
#
# DFLT_CONFIG_FILE = 'setup.cfg'
# DFLT_CONFIG_SECTION = 'metadata'
#
#
# # TODO: postprocess_ini_section_items and preprocess_ini_section_items: Add comma separated possibility?
# # TODO: Find out if configparse has an option to do this processing alreadys
# def postprocess_ini_section_items(items: Union[Mapping, Iterable]) -> Generator:
#     r"""Transform newline-separated string values into actual list of strings (assuming that intent)
#
#     >>> section_from_ini = {
#     ...     'name': 'epythet',
#     ...     'keywords': '\n\tdocumentation\n\tpackaging\n\tpublishing'
#     ... }
#     >>> section_for_python = dict(postprocess_ini_section_items(section_from_ini))
#     >>> section_for_python
#     {'name': 'epythet', 'keywords': ['documentation', 'packaging', 'publishing']}
#
#     """
#     splitter_re = re.compile('[\n\r\t]+')
#     if isinstance(items, Mapping):
#         items = items.items()
#     for k, v in items:
#         if v.startswith('\n'):
#             v = splitter_re.split(v[1:])
#             v = [vv.strip() for vv in v if vv.strip()]
#             v = [vv for vv in v if not vv.startswith('#')]  # remove commented lines
#         yield k, v
#
#
# def read_configs(
#         config_file=DFLT_CONFIG_FILE,
#         section=DFLT_CONFIG_SECTION,
#         postproc=postprocess_ini_section_items):
#     c = ConfigParser()
#     c.read_file(open(config_file, 'r'))
#     if section is None:
#         d = dict(c)
#         if postproc:
#             d = {k: dict(postproc(v)) for k, v in c}
#     else:
#         d = dict(c[section])
#         if postproc:
#             d = dict(postproc(d))
#     return d
#
#
# def diagnose_setup_kwargs(setup_kwargs):
#     """Diagnose setup_kwargs"""
#     _, containing_folder_name = os.path.split(os.path.dirname(__file__))
#     if setup_kwargs['name'] != containing_folder_name:
#         print(f"!!!! containing_folder_name={containing_folder_name} but setup name is {setup_kwargs['name']}")
#
#
# def my_setup(print_params=True, **setup_kwargs):
#     if print_params:
#         import json
#         print("Setup params -------------------------------------------------------")
#         print(json.dumps(setup_kwargs, indent=2))
#         print("--------------------------------------------------------------------")
#     setup(**setup_kwargs)
#
#
# def set_it_up():
#     setup_kwargs = read_configs()
#     diagnose_setup_kwargs(setup_kwargs)
#     my_setup(**setup_kwargs)

# set_it_up()
