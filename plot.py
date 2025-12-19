import matplotlib.pyplot as plt
from collections import deque
import time
import numpy as np

class LivePlotter:
    def __init__(self, max_points=200):
        self.max_points = max_points
        self.x_data = deque(maxlen=max_points)
        self.y_data = deque(maxlen=max_points)
        self.start_time = time.time()
        
        # setup styling
        plt.style.use('dark_background')
        plt.ion()
        
        self.fig, self.ax = plt.subplots(figsize=(10, 6))
        self.line, = self.ax.plot([], [], color='#00ffcc', linewidth=2, label='CO2 (mmHg)')
        
        # aesthetics
        self.ax.set_title('TrachSense Live CO2 Monitoring', fontsize=14, pad=20, color='white')
        self.ax.set_xlabel('Time (s)', fontsize=12, color='gray')
        self.ax.set_ylabel('Calibrated CO2 (mmHg)', fontsize=12, color='gray')
        self.ax.grid(True, linestyle='--', alpha=0.3)
        self.ax.legend(loc='upper right')
        
        # dynamic axis limits
        self.ax.set_ylim(0, 50) # default CO2 range, will auto-adjust if needed
        
        # prevent window from freezing
        self.fig.canvas.draw()
        plt.show(block=False)

    def update(self, calibrated_value):
        """adds a new data point and refreshes the plot."""
        current_time = time.time() - self.start_time
        self.x_data.append(current_time)
        self.y_data.append(calibrated_value)
        
        # update line data
        self.line.set_data(self.x_data, self.y_data)
        
        # auto-scrolling x-axis
        if len(self.x_data) > 0:
            self.ax.set_xlim(max(0, current_time - 20), current_time + 2)
        
        # auto-adjust y-axis if values exceed current limits
        if calibrated_value > self.ax.get_ylim()[1]:
            self.ax.set_ylim(0, calibrated_value * 1.2)
        
        # refresh
        self.fig.canvas.draw()
        self.fig.canvas.flush_events()
        plt.pause(0.001)

# global instance for the convenience function
_plotter_instance = None

def plot_live_co2(calibrated_value):
    """
    convenience function to plot a single co2 point live.
    usage: from plot import plot_live_co2; plot_live_co2(45.2)
    """
    global _plotter_instance
    if _plotter_instance is None:
        _plotter_instance = LivePlotter()
    _plotter_instance.update(calibrated_value)

# demo mode if run directly
if __name__ == "__main__":
    print("starting plot demo...")
    try:
        while True:
            # simulate a breathing wave
            t = time.time()
            sim_value = 20 + 15 * np.sin(2 * np.pi * 0.2 * t) + np.random.normal(0, 0.5)
            plot_live_co2(sim_value)
            time.sleep(0.04) # ~25fps
    except KeyboardInterrupt:
        print("\nplot demo stopped.")
