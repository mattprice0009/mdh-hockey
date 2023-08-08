from setuptools import find_packages, setup
from setuptools.command.install import install as _install


# Post-install script
def _post_install(install_dir):
  pass


class install(_install):

  def run(self):
    _install.run(self)
    self.execute(_post_install, (self.install_lib, ), msg="Running post install task")


package_data = []

setup(
  cmdclass={ 'install': install},
  name='mdhhockey',
  version='0.0.1',
  url='https://github.com/mattprice0009/mdh-hockey',
  packages=find_packages(where='.', exclude=[]),
  include_package_data=True,
  package_data={ 'mdhhockey': package_data},
  install_requires=[]
)
