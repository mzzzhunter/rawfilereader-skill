from setuptools import setup, find_packages

setup(
    name="rawfilereader-python",
    version="1.0.0",
    description="Python adapter for Thermo Fisher Scientific RawFileReader .NET assemblies",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    packages=find_packages(exclude=["tests*", "examples*"]),
    python_requires=">=3.8",
    install_requires=[
        "pythonnet>=3.0.3",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: Other/Proprietary License",
        "Operating System :: OS Independent",
        "Topic :: Scientific/Engineering :: Chemistry",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
    ],
)
