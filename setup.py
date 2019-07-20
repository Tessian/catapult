from setuptools import find_packages, setup

setup(
    name="catapult",
    packages=find_packages(),
    entry_points={"console_scripts": ["catapult=catapult.__main__:main"]},
)
