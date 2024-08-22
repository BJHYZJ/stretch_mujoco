"""
Python sample script for interfacing with the Stretch Mujoco simulator
"""

import signal
import sys
import threading
import time
from typing import Any, Dict

import click
import cv2
import mujoco
import mujoco.viewer
import numpy as np
import pkg_resources
from mujoco import MjData, MjModel

models_path = pkg_resources.resource_filename("stretch_mujoco", "models")
scene_xml_path = models_path + "/scene.xml"


@click.option("--scene-xml-path", default=scene_xml_path, help="Path to the scene xml file")
class StretchMujocoSimulator:
    """
    StretchMujocoSimulator sample class for simulating Stretch robot in Mujoco
    """

    def __init__(self, scene_xml_path: str = scene_xml_path):
        self.mjmodel = mujoco.MjModel.from_xml_path(scene_xml_path)
        self.mjdata = mujoco.MjData(self.mjmodel)

        self.rgb_renderer = mujoco.Renderer(self.mjmodel, height=480, width=640)
        self.depth_renderer = mujoco.Renderer(self.mjmodel, height=480, width=640)
        self.depth_renderer.enable_depth_rendering()
        self.wheel_diameter = 0.1016
        self.wheel_separation = 0.3153
        self.status = {
            "time": None,
            "base": {"x_vel": None, "theta_vel": None},
            "lift": {"pos": None, "vel": None},
            "arm": {"pos": None, "vel": None},
            "head_pan": {"pos": None, "vel": None},
            "head_tilt": {"pos": None, "vel": None},
            "wrist_yaw": {"pos": None, "vel": None},
            "wrist_pitch": {"pos": None, "vel": None},
            "wrist_roll": {"pos": None, "vel": None},
            "gripper": {"pos": None, "vel": None},
        }
        self._running = False
        self.viewer = mujoco.viewer
        signal.signal(signal.SIGINT, self.__signal_handler)

    def home(self) -> None:
        """
        Move the robot to home position
        """
        self.mjdata.ctrl = self.mjmodel.keyframe("home").ctrl

    def stow(self) -> None:
        """
        Move the robot to stow position
        """
        self.mjdata.ctrl = self.mjmodel.keyframe("stow").ctrl

    def move_to(self, actuator_name: str, pos: float) -> None:
        """
        Move the actuator to a specific position
        """
        self.mjdata.actuator(actuator_name).ctrl = pos

    def move_by(self, actuator_name: str, pos: float) -> None:
        """
        Move the actuator by a specific amount
        """
        self.mjdata.actuator(actuator_name).ctrl = self.status[actuator_name]["pos"] + pos

    def set_base_velocity(self, v_linear: float, omega: float) -> None:
        """
        Set the base velocity of the robot
        """
        w_left, w_right = self.diff_drive_inv_kinematics(v_linear, omega)
        self.mjdata.actuator("left_wheel_vel").ctrl = w_left
        self.mjdata.actuator("right_wheel_vel").ctrl = w_right

    def set_velocity(self, actuator_name: str, vel: float) -> None:
        """
        Set the velocity of the actuator
        """
        # TODO: Implement this method by ether moving to an integrated velocity acuators or have
        # separate robot xml configured by replacing position with velocity ctrl actuators
        raise NotImplementedError

    def get_base_pose(self) -> np.ndarray:
        """Get the se(2) base pose: x, y, and theta"""
        xyz = self.mjdata.body("base_link").xpos
        rotation = self.mjdata.body("base_link").xmat.reshape(3, 3)
        theta = np.arctan2(rotation[1, 0], rotation[0, 0])
        return np.array([xyz[0], xyz[1], theta])

    def get_ee_pose(self) -> np.ndarray:
        return self.get_link_pose("link_grasp_center")

    def get_link_pose(self, link_name: str) -> np.ndarray:
        """Get end effector pose as a 4x4 matrix"""
        xyz = self.mjdata.body(link_name).xpos
        rotation = self.mjdata.body(link_name).xmat.reshape(3, 3)
        pose = np.eye(4)
        pose[:3, :3] = rotation
        pose[:3, 3] = xyz
        return pose

    def pull_status(self) -> Dict[str, Any]:
        """
        Pull joints status of the robot from the simulator
        """
        self.status["time"] = self.mjdata.time
        self.status["lift"]["pos"] = self.mjdata.actuator("lift").length[0]
        self.status["lift"]["vel"] = self.mjdata.actuator("lift").velocity[0]

        self.status["arm"]["pos"] = self.mjdata.actuator("arm").length[0]
        self.status["arm"]["vel"] = self.mjdata.actuator("arm").velocity[0]

        self.status["head_pan"]["pos"] = self.mjdata.actuator("head_pan").length[0]
        self.status["head_pan"]["vel"] = self.mjdata.actuator("head_pan").velocity[0]

        self.status["head_tilt"]["pos"] = self.mjdata.actuator("head_tilt").length[0]
        self.status["head_tilt"]["vel"] = self.mjdata.actuator("head_tilt").velocity[0]

        self.status["wrist_yaw"]["pos"] = self.mjdata.actuator("wrist_yaw").length[0]
        self.status["wrist_yaw"]["vel"] = self.mjdata.actuator("wrist_yaw").velocity[0]

        self.status["wrist_pitch"]["pos"] = self.mjdata.actuator("wrist_pitch").length[0]
        self.status["wrist_pitch"]["vel"] = self.mjdata.actuator("wrist_pitch").velocity[0]

        self.status["wrist_roll"]["pos"] = self.mjdata.actuator("wrist_roll").length[0]
        self.status["wrist_roll"]["vel"] = self.mjdata.actuator("wrist_roll").velocity[0]

        self.status["gripper"]["pos"] = self.mjdata.actuator("gripper").length[0]
        self.status["gripper"]["vel"] = self.mjdata.actuator("gripper").velocity[0]

        left_wheel_vel = self.mjdata.actuator("left_wheel_vel").velocity[0]
        right_wheel_vel = self.mjdata.actuator("right_wheel_vel").velocity[0]
        (
            self.status["base"]["x_vel"],
            self.status["base"]["theta_vel"],
        ) = self.diff_drive_fwd_kinematics(left_wheel_vel, right_wheel_vel)

        return self.status

    def pull_camera_data(self) -> dict:
        """
        Pull camera data from the simulator
        """
        data = {}
        data["time"] = self.mjdata.time
        self.rgb_renderer.update_scene(self.mjdata, "d405_rgb")
        self.depth_renderer.update_scene(self.mjdata, "d405_rgb")
        data["cam_d405_rgb"] = cv2.cvtColor(self.rgb_renderer.render(), cv2.COLOR_RGB2BGR)
        data["cam_d405_depth"] = self.depth_renderer.render()

        self.rgb_renderer.update_scene(self.mjdata, "d435i_camera_rgb")
        self.depth_renderer.update_scene(self.mjdata, "d435i_camera_rgb")
        data["cam_d435i_rgb"] = cv2.rotate(
            cv2.cvtColor(self.rgb_renderer.render(), cv2.COLOR_RGB2BGR),
            cv2.ROTATE_90_COUNTERCLOCKWISE,
        )
        data["cam_d435i_depth"] = cv2.rotate(
            self.depth_renderer.render(), cv2.ROTATE_90_COUNTERCLOCKWISE
        )

        self.rgb_renderer.update_scene(self.mjdata, "nav_camera_rgb")
        data["cam_nav_rgb"] = cv2.cvtColor(self.rgb_renderer.render(), cv2.COLOR_RGB2BGR)
        return data

    def __ctrl_callback(self, model: MjModel, data: MjData) -> None:
        """
        Callback function that gets executed with mj_step
        """
        self.mjdata = data
        self.mjmodel = model
        self.pull_status()

    def diff_drive_inv_kinematics(self, V: float, omega: float) -> tuple:
        """
        Calculate the rotational velocities of the left and right wheels for a
        differential drive robot.
        """
        R = self.wheel_diameter / 2
        L = self.wheel_separation
        if R <= 0:
            raise ValueError("Radius must be greater than zero.")
        if L <= 0:
            raise ValueError("Distance between wheels must be greater than zero.")

        # Calculate the rotational velocities of the wheels
        w_left = (V - (omega * L / 2)) / R
        w_right = (V + (omega * L / 2)) / R

        return (w_left, w_right)

    def diff_drive_fwd_kinematics(self, w_left: float, w_right: float) -> tuple:
        """
        Calculate the linear and angular velocity of a differential drive robot.
        """
        R = self.wheel_diameter / 2
        L = self.wheel_separation
        if R <= 0:
            raise ValueError("Radius must be greater than zero.")
        if L <= 0:
            raise ValueError("Distance between wheels must be greater than zero.")

        # Linear velocity (V) is the average of the linear velocities of the two wheels
        V = R * (w_left + w_right) / 2.0

        # Angular velocity (omega) is the difference in linear velocities divided by the distance
        # between the wheels
        omega = R * (w_right - w_left) / L

        return (V, omega)

    def __run(self) -> None:
        mujoco.set_mjcb_control(self.__ctrl_callback)
        self.viewer.launch(self.mjmodel)

    def __signal_handler(self, signal, frame) -> None:
        click.secho("Exiting Stretch Mujoco Simulator...", fg="red")
        self._running = False
        sys.exit(0)

    def is_running(self) -> bool:
        """
        Check if the simulator is running
        """
        return self._running

    def start(self) -> None:
        """
        Start the simulator in a using blocking Managed-vieiwer for precise timing. And user code
        is looped through callback. Some projects might need non-blocking Passive-vieiwer.
        For more info visit: https://mujoco.readthedocs.io/en/stable/python.html#managed-viewer
        """
        threading.Thread(target=self.__run).start()
        time.sleep(0.5)
        self._running = True
        self.home()

    def stop(self) -> None:
        """
        Stop the simulator
        """
        self._running = False


@click.command()
@click.option("--scene-xml-path", default=scene_xml_path, help="Path to the scene xml file")
def main(scene_xml_path: str) -> None:
    robot_sim = StretchMujocoSimulator()
    robot_sim.start()
    # display camera feeds
    try:
        while robot_sim.is_running():
            camera_data = robot_sim.pull_camera_data()
            cv2.imshow("cam_d405_rgb", camera_data["cam_d405_rgb"])
            cv2.imshow("cam_d405_depth", camera_data["cam_d405_depth"])
            cv2.imshow("cam_d435i_rgb", camera_data["cam_d435i_rgb"])
            cv2.imshow("cam_d435i_depth", camera_data["cam_d435i_depth"])
            cv2.imshow("cam_nav_rgb", camera_data["cam_nav_rgb"])
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    except KeyboardInterrupt:
        robot_sim.stop()
        cv2.destroyAllWindows()
        exit(0)


if __name__ == "__main__":
    main()
