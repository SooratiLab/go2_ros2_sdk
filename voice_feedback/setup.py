from setuptools import find_packages, setup

package_name = 'voice_feedback'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ilana',
    maintainer_email='ilaana200@gmail.com',
    description='Decipher Nav2 odom and provides voice feedback for the dog.',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'decipher_movements_node = voice_feedback.decipher_movements_node:main',
            'speech_announcer_node = voice_feedback.speech_announcer_node:main',
        ],
    },
)
