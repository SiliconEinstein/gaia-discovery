# K=0 Eigenstates of the Josephson Tunneling Hamiltonian

## 0. Setup

The two-component macroscopic wavefunction:

$$\Psi = \begin{pmatrix} \Psi_1 \\ \Psi_2 \end{pmatrix} = \begin{pmatrix} |\Delta_1| e^{i\phi_1} \\ |\Delta_2| e^{i\phi_2} \end{pmatrix}$$

where $\Delta_j = \sqrt{n_{s,j}/2} \, e^{i\phi_j}$ is the spatially uniform order parameter on side $j=1,2$, and $n_{s,j}$ is the Cooper-pair superfluid density.

The Hamiltonian (energy per Cooper pair):

$$H = \begin{pmatrix} eV & K \\ K & -eV \end{pmatrix}$$

At $K=0$ (no tunneling):

$$H_{K=0} = \begin{pmatrix} eV & 0 \\ 0 & -eV \end{pmatrix} = \operatorname{diag}(eV, -eV)$$

## 1. Eigenvalue Problem

The time-independent Schrodinger equation $H\psi = E\psi$ at $K=0$:

$$\begin{pmatrix} eV & 0 \\ 0 & -eV \end{pmatrix} \begin{pmatrix} a \\ b \end{pmatrix} = E \begin{pmatrix} a \\ b \end{pmatrix}$$

which decouples into:

$$eV \cdot a = E a, \qquad -eV \cdot b = E b$$

### Case 1: $a \neq 0, b = 0$

$$E = +eV,\quad \psi_1 = \begin{pmatrix} 1 \\ 0 \end{pmatrix}$$

Normalized eigenstate (up to overall phase):

$$\psi_1 = \begin{pmatrix} 1 \\ 0 \end{pmatrix}, \qquad E_1 = +eV$$

### Case 2: $a = 0, b \neq 0$

$$E = -eV,\quad \psi_2 = \begin{pmatrix} 0 \\ 1 \end{pmatrix}$$

Normalized eigenstate (up to overall phase):

$$\psi_2 = \begin{pmatrix} 0 \\ 1 \end{pmatrix}, \qquad E_2 = -eV$$

### Degeneracy check

If $eV = 0$, then $H = 0$ (the zero matrix) and *any* vector is an eigenvector with $E = 0$ -- infinite degeneracy. For $eV \neq 0$, the eigenvalues $\pm eV$ are distinct and the eigenvectors form a complete orthonormal basis.

## 2. Physical Interpretation of Eigenstates

### $\psi_1 = (1, 0)^T$ (energy $E_1 = +eV$)

The wavefunction is:
$$\Psi = \begin{pmatrix} \Delta_1 \\ 0 \end{pmatrix}$$

This means:
- The Cooper pair resides **entirely on side 1** of the junction.
- $\Delta_1 \neq 0$, $\Delta_2 = 0$
- $n_{s,1} = 2| \Delta_1|^2 = n_{s,\text{total}}$, $n_{s,2} = 0$
- The superfluid density is fully localized in electrode 1.
- Energy $E_1 = +eV$: if $V>0$, side 1 has higher electrostatic potential (electrons at higher energy).

### $\psi_2 = (0, 1)^T$ (energy $E_2 = -eV$)

The wavefunction is:
$$\Psi = \begin{pmatrix} 0 \\ \Delta_2 \end{pmatrix}$$

This means:
- The Cooper pair resides **entirely on side 2** of the junction.
- $\Delta_1 = 0$, $\Delta_2 \neq 0$
- $n_{s,1} = 0$, $n_{s,2} = 2|\Delta_2|^2 = n_{s,\text{total}}$
- The superfluid density is fully localized in electrode 2.
- Energy $E_2 = -eV$: if $V>0$, side 2 has lower electrostatic potential.

### Summary table

| Eigenstate | Components | Energy | Cooper pair location | $n_{s,1}$ | $n_{s,2}$ |
|------------|-----------|--------|---------------------|------------|------------|
| $\psi_1$   | $\Delta_1 \neq 0$, $\Delta_2 = 0$ | $+eV$ | Side 1 only | $n_{s,\text{total}}$ | $0$ |
| $\psi_2$   | $\Delta_1 = 0$, $\Delta_2 \neq 0$ | $-eV$ | Side 2 only | $0$ | $n_{s,\text{total}}$ |

## 3. Superfluid Density Conservation

The macroscopic wavefunction normalization:

$$|\Psi|^2 = |\Delta_1|^2 + |\Delta_2|^2 = \text{const}$$

This normalization reflects conservation of the total superfluid Cooper-pair density: in a closed two-reservoir system with no pair-breaking or injection, Cooper pairs are neither created nor destroyed.

Substitute the relation between $|\Delta_j|$ and $n_{s,j}$:

$$|\Delta_j|^2 = \frac{n_{s,j}}{2}$$

The normalization condition becomes:

$$|\Delta_1|^2 + |\Delta_2|^2 = \frac{n_{s,1}}{2} + \frac{n_{s,2}}{2} = \frac{n_{s,1} + n_{s,2}}{2} = \text{const}$$

Multiply by 2:

$$\boxed{n_{s,1} + n_{s,2} = \text{const}}$$

where the constant is the total superfluid Cooper-pair density $n_{s,\text{total}}$.

### Physical meaning

- $n_{s,1} + n_{s,2} = n_{s,\text{total}}$ is a **global conservation law** for the superfluid density.
- In the $K=0$ eigenstates, the constant takes extreme values: either $(n_{s,\text{total}}, 0)$ or $(0, n_{s,\text{total}})$.
- For general (non-eigenstate) wavefunctions at $K=0$, any superposition $\alpha \psi_1 + \beta \psi_2$ with $|\alpha|^2 + |\beta|^2 = 1$ satisfies $n_{s,1} + n_{s,2} = n_{s,\text{total}}$, where $n_{s,1} = 2|\alpha|^2 |\Delta_1|^2$ and $n_{s,2} = 2|\beta|^2 |\Delta_2|^2$ are time-independent because the Hamiltonian is diagonal.
- When $K \neq 0$, the tunneling term couples the two reservoirs and $n_{s,1}$ and $n_{s,2}$ become time-dependent, but $n_{s,1} + n_{s,2}$ remains conserved (as will be verified in sub-question (e) by deriving $dn_{s,1}/dt = -dn_{s,2}/dt$).

## 4. Eigenstate-Limit Relationship

For completeness, consider the full Hamiltonian with $K \neq 0$:

$$H = \begin{pmatrix} eV & K \\ K & -eV \end{pmatrix}$$

The eigenvalues are:

$$E_{\pm} = \pm \sqrt{e^2 V^2 + K^2}$$

Introduce the mixing angle $\alpha$ defined by:

$$\tan \alpha = \frac{K}{eV}, \quad \sin \alpha = \frac{K}{\sqrt{e^2 V^2 + K^2}}, \quad \cos \alpha = \frac{eV}{\sqrt{e^2 V^2 + K^2}}$$

The normalized eigenstates are:

$$\psi_+ = \begin{pmatrix} \cos(\alpha/2) \\ \sin(\alpha/2) \end{pmatrix}, \quad E_+ = +\sqrt{e^2 V^2 + K^2}$$

$$\psi_- = \begin{pmatrix} \sin(\alpha/2) \\ -\cos(\alpha/2) \end{pmatrix}, \quad E_- = -\sqrt{e^2 V^2 + K^2}$$

### Limit $K \to 0$ (with $eV \neq 0$)

- $\tan \alpha \to 0$, so $\alpha \to 0$, $\cos(\alpha/2) \to 1$, $\sin(\alpha/2) \to 0$
- $\psi_+ \to (1, 0)^T = \psi_1$, $E_+ \to |eV| = +eV$ (assuming $eV > 0$)
- $\psi_- \to (0, -1)^T \propto \psi_2$, $E_- \to -|eV| = -eV$

The relative minus sign in $\psi_-$ is physically irrelevant (global phase). For $eV < 0$, the roles swap: $\psi_+ \to (0, 1)^T$ and $\psi_- \to (-1, 0)^T$, matching the $K=0$ analysis with the sign reversal taken into account.

**Key conclusion**: The $K=0$ eigenstates $\psi_1 = (1,0)^T$ and $\psi_2 = (0,1)^T$ are precisely the $K \to 0$ limits of the finite-$K$ eigenstates. The $K=0$ basis is the "localized" (definite-electrode) basis, and the finite-$K$ eigenstates are superpositions of these localized states with mixing angle controlled by $K/eV$.

### Limit $eV \to 0$ (zero bias)

- $\tan \alpha \to \infty$, so $\alpha \to \pi/2$, $\cos(\alpha/2) = \sin(\alpha/2) = 1/\sqrt{2}$
- $\psi_+ = (1/\sqrt{2}, 1/\sqrt{2})^T$, $E_+ = |K|$
- $\psi_- = (1/\sqrt{2}, -1/\sqrt{2})^T$, $E_- = -|K|$

These are the symmetric and antisymmetric superpositions, corresponding to the bonding (lower energy) and antibonding (higher energy) states of the double-well potential. The Cooper pair is equally shared between the two electrodes.

## 5. Verification Checks

1. **Orthonormality**: $\psi_1^\dagger \psi_1 = 1$, $\psi_2^\dagger \psi_2 = 1$, $\psi_1^\dagger \psi_2 = 0$ -- verified.
2. **Completeness**: $\psi_1 \psi_1^\dagger + \psi_2 \psi_2^\dagger = \operatorname{diag}(1,0) + \operatorname{diag}(0,1) = I_2$ -- verified.
3. **Eigenvalue equation**: $H\psi_1 = \operatorname{diag}(eV,-eV)(1,0)^T = (eV, 0)^T = eV \cdot (1,0)^T$ -- verified. Similarly for $\psi_2$.
4. **Continuity of $K \to 0$ limit**: $E_{\pm} = \pm\sqrt{e^2 V^2 + K^2} \to \pm|eV| = \pm eV$ (for $eV>0$), matching the $K=0$ eigenvalues.
5. **Conservation law**: $|\Delta_1|^2 + |\Delta_2|^2 = (n_{s,1} + n_{s,2})/2 = \text{const} \implies n_{s,1} + n_{s,2} = \text{const}$, verified from $| \Psi|^2 = \text{const}$.

## 6. Conclusion

At $K=0$, the Josephson tunneling Hamiltonian $H = \operatorname{diag}(eV, -eV)$ has eigenstates $\psi_1 = (1,0)^T$ (Cooper pair on side 1, energy $+eV$) and $\psi_2 = (0,1)^T$ (Cooper pair on side 2, energy $-eV$). These represent fully localized superfluid states. The wavefunction normalization $|\Delta_1|^2 + |\Delta_2|^2 = \text{const}$ together with $|\Delta_j|^2 = n_{s,j}/2$ implies total superfluid density conservation $n_{s,1} + n_{s,2} = \text{const}$. The $K=0$ eigenstates are the $K \to 0$ limits of the finite-$K$ mixed eigenstates.
