import { useState } from 'react'
import reactLogo from './assets/react.svg'
import viteLogo from './assets/vite.svg'
import heroImg from './assets/hero.png'
import './App.css'

function App() {
  const [formData, setFormData] = useState({
    memberId: "",
    policyId: "PLUM_GHI_2024",
    claimCategory: "CONSULTATION",
    treatmentDate: "",
    claimedAmount: "",
  });

  const [files, setFiles] = useState([]);

  const handleChange = (e) => {
    setFormData((prev) => ({
      ...prev,
      [e.target.name]: e.target.value,
    }));
  };

  const handleFileChange = (e) => {
    setFiles(Array.from(e.target.files));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    const data = new FormData();

    Object.entries(formData).forEach(([key, value]) => {
      data.append(key, value);
    });

    files.forEach((file) => {
      data.append("documents", file);
    });

    try {
      const res = await fetch("http://localhost:8000/claim", {
        method: "POST",
        body: data,
      });
      console.log(res);
      const result = await res.json();
      console.log(result);
      alert("Claim submitted");
    } catch (err) {
      console.error(err);
      alert("Submission failed");
    }
  };

  return (
    <div style={{ maxWidth: 700, margin: "auto", padding: 20 }}>
      <h2>Health Insurance Claim</h2>

      <form onSubmit={handleSubmit}>
        <div>
          <label>Member ID</label>
          <input
            name="memberId"
            value={formData.memberId}
            onChange={handleChange}
            required
          />
        </div>

        <div>
          <label>Policy ID</label>
          <input
            name="policyId"
            value={formData.policyId}
            onChange={handleChange}
            required
          />
        </div>

        <div>
          <label>Claim Category</label>
          <select
            name="claimCategory"
            value={formData.claimCategory}
            onChange={handleChange}
          >
            <option value="CONSULTATION">Consultation</option>
            <option value="PHARMACY">Pharmacy</option>
            <option value="DIAGNOSTIC">Diagnostic</option>
            <option value="DENTAL">Dental</option>
            <option value="VISION">Vision</option>
            <option value="ALTERNATIVE_MEDICINE">
              Alternative Medicine
            </option>
          </select>
        </div>

        <div>
          <label>Treatment Date</label>
          <input
            type="date"
            name="treatmentDate"
            value={formData.treatmentDate}
            onChange={handleChange}
            required
          />
        </div>

        <div>
          <label>Claimed Amount</label>
          <input
            type="number"
            name="claimedAmount"
            value={formData.claimedAmount}
            onChange={handleChange}
            required
          />
        </div>

        <div>
          <label>Documents (PDF/JPG/PNG)</label>
          <input
            type="file"
            multiple
            accept=".pdf,.jpg,.jpeg,.png"
            onChange={handleFileChange}
            required
          />
        </div>

        <br />

        <button type="submit">
          Submit Claim
        </button>
      </form>

      <hr />

      <h3>Uploaded Files</h3>

      {files.map((file) => (
        <div key={file.name}>
          {file.name} ({Math.round(file.size / 1024)} KB)
        </div>
      ))}
    </div>
  );
}

export default App
