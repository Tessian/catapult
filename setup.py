from setuptools import setup, find_packages

setup(
    name="catapult",
    packages=find_packages(),
    entry_points={"console_scripts": ["catapult=catapult.__main__:main"]},
)
