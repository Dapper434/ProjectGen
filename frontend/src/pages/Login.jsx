import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function Login() {
  const [username, setUsername] = useState('producer');
  const [password, setPassword] = useState('demo');
  const [role, setRole] = useState('Producer');
  const navigate = useNavigate();
  const [error, setError] = useState('');

  const handleLogin = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch('http://localhost:5000/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, role }),
        credentials: 'include'
      });
      if (res.ok) {
        navigate('/dashboard');
      } else {
        setError('Invalid credentials');
      }
    } catch (err) {
      setError('Connection failed');
    }
  };

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-zinc-900 border border-zinc-800 rounded-xl p-8 shadow-2xl">
        <div className="mb-10 text-center">
          <div className="w-12 h-12 bg-indigo-600 rounded-lg flex items-center justify-center font-bold text-white text-xl tracking-tighter mx-auto mb-4">
            F.OS
          </div>
          <h1 className="text-2xl font-semibold text-white tracking-tight">Welcome to FactoryOS</h1>
          <p className="text-zinc-400 mt-2 text-sm">GDF Kenya internal platform</p>
        </div>

        {error && <div className="mb-4 p-3 bg-red-950/50 border border-red-900/50 text-red-400 text-sm rounded-md">{error}</div>}

        <form onSubmit={handleLogin} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-1.5">Username</label>
            <input 
              type="text" 
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-4 py-2.5 text-zinc-100 focus:outline-none focus:border-indigo-500 transition-colors"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-1.5">Password</label>
            <input 
              type="password" 
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-4 py-2.5 text-zinc-100 focus:outline-none focus:border-indigo-500 transition-colors"
            />
          </div>
          
          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-1.5">Login As (Demo)</label>
            <select 
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-4 py-2.5 text-zinc-100 focus:outline-none focus:border-indigo-500 transition-colors appearance-none"
            >
              <option value="Producer">Producer</option>
              <option value="Account Manager">Account Manager</option>
            </select>
          </div>

          <button 
            type="submit"
            className="w-full bg-white text-zinc-950 font-semibold py-2.5 rounded-md hover:bg-zinc-200 transition-colors mt-4"
          >
            Sign In
          </button>
        </form>
      </div>
    </div>
  );
}
