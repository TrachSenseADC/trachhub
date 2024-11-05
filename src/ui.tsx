import React, { useState } from 'react';
import MoonLoader from 'react-spinners/MoonLoader';

interface TrachHubUIProps {}

const TrachHubUI: React.FC<TrachHubUIProps> = () => {
    const orange = '#FFA500';
    const green = '#88E788';
    const red = '#ED4337';

    const [connectionMode, setConnectionMode] = useState<'WiFi' | 'Bluetooth'>('WiFi');
    const [status, setStatus] = useState<'Connected' | 'Disconnected' | 'Connecting'>('Disconnected');    
    const [mobileInRange, setMobileInRange] = useState(false);
    const [color, setColor] = useState(red);
    const [options, setOptions] = useState<'Disconnect' | 'Connect'>('Connect');



    // TBI:
    // 1. Logic to handle connection statuses (is the TrachSense device connected or disconnected?)
    // 2. Logic to handle range statuses (is the mobile device in range or out of range?)
    // 3. Feature to add mobile device for bluetooth
    // 4. Feature to add wifi connection

    const handleConnectionToggle = () => {
        // This is to emulate connecting
        if (options === 'Connect') {
            setStatus('Connecting');
            setColor(orange);
            
            setTimeout(() => {
                setConnectionMode(mobileInRange ? 'Bluetooth' : 'WiFi');
                setStatus('Connected');
                setColor(green);
                setOptions('Disconnect');
            }, 1500);
        } else {
            // This is to emulate disconnection
            setStatus('Disconnected');
            setColor(red);
            setOptions('Connect');
        }
    };
    const handleModeSwitch = (isBluetooth: boolean) => {
        setStatus('Connecting');
        setColor(orange);

        setTimeout(() => {
            setMobileInRange(isBluetooth);
            setConnectionMode(isBluetooth ? 'Bluetooth' : 'WiFi');
            setStatus('Connected');
            setOptions('Disconnect');
            setColor(green);
        }, 1500);
    };
    return (
        <div className="font-sans p-4 text-center">
            {/* Status */}
            <div style={{ backgroundColor: '#5E514D' }} className="text-white p-4 rounded-md">
                <h1 className="text-2xl font-bold mb-2">TrachHub Interface</h1>
                <p className="mb-1">Mode: {connectionMode}</p>
                <p>Status: {status}</p>
                <div className="flex mt-2">
                    <div
                        style={{
                            width: '30px',
                            height: '30px',
                            borderRadius: '50%',
                            backgroundColor: color,
                        }}
                    ></div>
                </div>
            </div>

            {/* Info Section */}
            <div className="mt-6 p-4 border border-gray-300 rounded-md">
                <h2 className="text-xl font-semibold mb-4">Connected Devices</h2>
                <div className="mb-4">
                    <p><strong>Medical Device:</strong> XYZ-1234</p>
                    <p><strong>Status:</strong> {status}</p>
                </div>
                <div>
                    <p className="mb-2"><strong>Mobile Device:</strong> {mobileInRange ? "In Range" : "Out of Range"}</p>
                    <button
                        onClick={handleConnectionToggle}
                        className="bg-blue-500 text-white px-4 py-2 rounded-md hover:bg-blue-600 transition-colors "
                        disabled={status === 'Connecting'}
                    >
                        {status === 'Connecting' ? (
                            <div className='flex'>
                            <MoonLoader size={20} color='white' />
                          </div>
                        ) : (
                            options
                        )}
                    </button>
                </div>
            </div>

            {/* Connection Type Section */}
            <div className="mt-6">
                <h3 className="text-lg font-semibold mb-3">Connection Mode</h3>
                <button
                    onClick={() => handleModeSwitch(false)}
                    className="bg-gray-200 px-4 py-2 rounded-md mr-2 hover:bg-gray-300 transition-colors"
                    disabled={status === 'Connecting'}
                >
                    Switch to WiFi
                </button>
                <button
                    onClick={() => handleModeSwitch(true)}
                    className="bg-gray-200 px-4 py-2 rounded-md hover:bg-gray-300 transition-colors"
                    disabled={status === 'Connecting'}
                >
                    Switch to Bluetooth
                </button>
            </div>

            {/* Notifications Section */}
            <div className="mt-6 p-4 bg-gray-100 rounded-md">
                <h3 className="text-lg font-semibold mb-3">Notifications</h3>
                <p>
                    {status === 'Connecting' 
                        ? "Establishing connection..." 
                        : mobileInRange
                            ? "Connected via Bluetooth to Mobile Device."
                            : "Mobile Device Out of Range. Connected via WiFi."}
                </p>
            </div>
        </div>
    );
};

export default TrachHubUI;
